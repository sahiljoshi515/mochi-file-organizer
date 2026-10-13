"""The organizing rules (src/plugin/RULES.md), applied the same way by the tools and the verifier.

src/plugin/rules.py is a byte-identical copy of this file (tests/test_rules.py asserts it), so the
reference tool, the inventory and the checks all decide from one piece of code. It uses only what a
verifier may: pathlib reads, hashlib, re, json and unicodedata. UTC dates are computed by arithmetic
(no datetime), a zip's central directory and a JPEG's EXIF segment are read by hand (no zipfile,
struct or Pillow).
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

# How many files each size of messy folder holds.
COUNTS = {"small": 60, "medium": 150, "large": 300}
INBOX = "inbox"
ORGANIZED = "organized"
ROOT = re.compile(r"^file-organizer/(\d{1,9})-(small|medium|large)$")

# Content types in sniffing order, each with its category folder; the final extension is the type.
CATEGORIES = {
    "pdf": "documents/pdf",
    "png": "images/png",
    "jpg": "images/jpg",
    "docx": "documents/docx",
    "zip": "archives/zip",
    "svg": "images/svg",
    "html": "documents/html",
    "py": "code/py",
    "json": "data/json",
    "log": "logs/log",
    "md": "documents/md",
    "csv": "data/csv",
    "txt": "documents/txt",
    "bin": "other/bin",
}
JUNK_NAMES = frozenset({".ds_store", "thumbs.db", "desktop.ini"})
JUNK_EXTS = frozenset({"tmp", "part"})
COPY_MARKERS = re.compile(r"(\s*\(\d+\)|\s*-\s*copy(\s*\(\d+\))?|[\s_-]+copy\d*|[-_ ]?(final|v\d+))$")
NAME_DATE = re.compile(r"(?<!\d)(?:(\d{4})-(\d{2})-(\d{2})|(\d{4})(\d{2})(\d{2}))(?!\d)")
CLAIMED_EXT = re.compile(r"^(.+)\.([A-Za-z0-9]{1,10})$")
NOT_SLUG = re.compile(r"[^a-z0-9]+")
EMPTY_SLUG = "file"
MIN_YEAR, MAX_YEAR = 1990, 2030
TARGET = re.compile(r"^organized/([a-z]+/[a-z]+)/(\d{4})/(\d{4})-(\d{2})-(\d{2})_([a-z0-9]+(?:-[a-z0-9]+)*)\.([a-z]+)$")

SVG_START = re.compile(r"(?:<\?xml[^>]*\?>\s*)?<svg[\s>]", re.IGNORECASE)
HTML_START = re.compile(r"(?:<!doctype\s+html|<html)[\s>]", re.IGNORECASE)
LOG_START = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")
EXIF_DATE = re.compile(r"(\d{4}):(\d{2}):(\d{2})")
ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?!\d)")
RFC_DATE = re.compile(r"(?:[A-Za-z]{3},\s*)?(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})")
PDF_DATE_VALUE = re.compile(r"D:(\d{4})(\d{2})(\d{2})")
PDF_CREATION = re.compile(rb"/CreationDate\s*\(([^)]*)\)")
FRONT_DATE = re.compile(r"date:[ \t]*(.*?)[ \t]*$")
MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


@dataclass(frozen=True)
class Row:
    """One file as the inventory describes it: everything the rules decide from."""

    path: str
    size: int
    sha256: str
    type: str
    ext: str
    exif: str | None
    png: str | None
    pdf: str | None
    md: str | None
    mtime_utc: str


@dataclass(frozen=True)
class Plan:
    """What the rules do with a folder: every kept file's move, every deletion, and the final layout."""

    moves: tuple[tuple[str, str], ...]  # (from, to) in naming order
    deletes: tuple[str, ...]  # junk, empty files and extra copies, sorted
    expected: tuple[tuple[str, str], ...]  # (sha256, final path), sorted by path
    unique: int
    duplicates: int
    removed: int


def root_name(seed: int, size: str) -> str:
    return f"file-organizer/{seed}-{size}"


def file_name(path: str) -> str:
    return path.rpartition("/")[2]


# ----- Sniffing (rule 2) -----


def as_text(data: bytes) -> str | None:
    """`data` as UTF-8 text, or None when it does not decode or holds a NUL byte."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return None if "\x00" in text else text


def zip_names(data: bytes) -> list[str]:
    """The entry names in a zip's central directory, read by hand; [] when there is none."""
    end = data.rfind(b"PK\x05\x06")
    if end < 0 or len(data) < end + 22:
        return []
    count = int.from_bytes(data[end + 10 : end + 12], "little")
    offset = int.from_bytes(data[end + 16 : end + 20], "little")
    names = []
    for _index in range(min(count, 4096)):
        if data[offset : offset + 4] != b"PK\x01\x02" or len(data) < offset + 46:
            break
        name_len = int.from_bytes(data[offset + 28 : offset + 30], "little")
        extra_len = int.from_bytes(data[offset + 30 : offset + 32], "little")
        comment_len = int.from_bytes(data[offset + 32 : offset + 34], "little")
        names.append(data[offset + 46 : offset + 46 + name_len].decode("utf-8", "replace"))
        offset += 46 + name_len + extra_len + comment_len
    return names


def is_json(text: str) -> bool:
    try:
        json.loads(text)
    except ValueError:
        return False
    return True


def is_csv(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    commas = {line.count(",") for line in lines}
    return len(lines) >= 3 and len(commas) == 1 and commas.pop() >= 1


def sniff(data: bytes) -> str:
    """The content type of `data`, in the rules' order."""
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"PK\x03\x04"):
        return "docx" if "word/document.xml" in zip_names(data) else "zip"
    text = as_text(data)
    if text is None:
        return "bin"
    head = text.lstrip()
    first = text.split("\n", 1)[0].rstrip("\r")
    if SVG_START.match(head):
        return "svg"
    if HTML_START.match(head):
        return "html"
    if first.startswith("#!") and "python" in first.lower():
        return "py"
    if head.startswith(("{", "[")) and is_json(text):
        return "json"
    if LOG_START.match(first):
        return "log"
    if first.startswith("# ") or first == "---":
        return "md"
    if is_csv(text):
        return "csv"
    return "txt"


# ----- Embedded dates, as stored -----


def exif_datetime(data: bytes) -> str | None:
    """DateTimeOriginal (tag 0x9003) from a JPEG's APP1 Exif segment, as stored; None without one."""
    offset = 2
    while offset + 4 <= len(data) and data[offset] == 0xFF:
        marker = data[offset + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            offset += 2
            continue
        if marker in (0xDA, 0xD9):
            break
        length = int.from_bytes(data[offset + 2 : offset + 4], "big")
        segment = data[offset + 4 : offset + 2 + length]
        if marker == 0xE1 and segment.startswith(b"Exif\x00\x00"):
            return tiff_datetime(segment[6:])
        offset += 2 + length
    return None


def tiff_datetime(tiff: bytes) -> str | None:
    """DateTimeOriginal from a TIFF structure: IFD0's Exif pointer (0x8769), then tag 0x9003."""
    endian = {b"II": "little", b"MM": "big"}.get(tiff[:2])
    if endian is None:
        return None

    def number(start: int, width: int) -> int:
        return int.from_bytes(tiff[start : start + width], endian)

    def entries(ifd: int) -> list[int]:
        count = number(ifd, 2)
        return [ifd + 2 + 12 * index for index in range(min(count, 512))]

    exif_ifd = None
    for entry in entries(number(4, 4)):
        if number(entry, 2) == 0x8769:
            exif_ifd = number(entry + 8, 4)
    if exif_ifd is None:
        return None
    for entry in entries(exif_ifd):
        if number(entry, 2) == 0x9003 and number(entry + 2, 2) == 2:
            count = number(entry + 4, 4)
            start = entry + 8 if count <= 4 else number(entry + 8, 4)
            return tiff[start : start + count].split(b"\x00", 1)[0].decode("ascii", "replace").strip()
    return None


def png_creation_time(data: bytes) -> str | None:
    """The `Creation Time` tEXt chunk of a PNG, as stored; None without one."""
    offset = 8
    while offset + 8 <= len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        kind = data[offset + 4 : offset + 8]
        if kind == b"IEND":
            break
        if kind == b"tEXt":
            keyword, _sep, text = data[offset + 8 : offset + 8 + length].partition(b"\x00")
            if keyword == b"Creation Time":
                return text.decode("latin-1")
        offset += 12 + length
    return None


def pdf_creation_date(data: bytes) -> str | None:
    """The `/CreationDate (...)` string of a PDF, as stored; None without one."""
    found = PDF_CREATION.search(data)
    return found.group(1).decode("latin-1") if found else None


def frontmatter_date(text: str) -> str | None:
    """The `date:` value of a Markdown file's front matter, as written; None without one."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        found = FRONT_DATE.match(line)
        if found:
            return found.group(1)
    return None


# ----- Dates (rule 3) -----


def days_in_month(year: int, month: int) -> int:
    if month == 2:
        return 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28
    return 30 if month in (4, 6, 9, 11) else 31


def valid_date(year: int, month: int, day: int) -> bool:
    return 1 <= month <= 12 and 1 <= day <= days_in_month(year, month)


def iso(year: int, month: int, day: int) -> str:
    return f"{year:04d}-{month:02d}-{day:02d}"


def real_date(year: int, month: int, day: int) -> str | None:
    return iso(year, month, day) if valid_date(year, month, day) else None


def civil(days: int) -> tuple[int, int, int]:
    """The calendar date `days` after 1970-01-01, proleptic Gregorian (Howard Hinnant's algorithm)."""
    days += 719468
    era = days // 146097
    doe = days - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    day = doy - (153 * mp + 2) // 5 + 1
    month = mp + 3 if mp < 10 else mp - 9
    return yoe + era * 400 + (1 if month <= 2 else 0), month, day


def utc_stamp(seconds: int) -> str:
    """Whole seconds since the epoch as `YYYY-MM-DDTHH:MM:SSZ`."""
    days, rest = divmod(seconds, 86400)
    year, month, day = civil(days)
    hour, rest = divmod(rest, 3600)
    minute, second = divmod(rest, 60)
    return f"{iso(year, month, day)}T{hour:02d}:{minute:02d}:{second:02d}Z"


def embedded_date(row: Row) -> str | None:
    """The date of the first embedded value that is a real date: exif, then png, then pdf, then md."""
    if row.exif:
        found = EXIF_DATE.match(row.exif)
        if found and real_date(*map(int, found.groups())):
            return iso(*map(int, found.groups()))
    if row.png:
        found = ISO_DATE.match(row.png)
        if found and real_date(*map(int, found.groups())):
            return iso(*map(int, found.groups()))
        found = RFC_DATE.match(row.png)
        if found and found.group(2).lower() in MONTHS:
            year, month, day = int(found.group(3)), MONTHS[found.group(2).lower()], int(found.group(1))
            if valid_date(year, month, day):
                return iso(year, month, day)
    if row.pdf:
        found = PDF_DATE_VALUE.match(row.pdf)
        if found and real_date(*map(int, found.groups())):
            return iso(*map(int, found.groups()))
    if row.md:
        found = ISO_DATE.match(row.md.strip().strip("'\""))
        if found and real_date(*map(int, found.groups())):
            return iso(*map(int, found.groups()))
    return None


def name_date(name: str) -> str | None:
    """The first real date in a file name, `YYYY-MM-DD` or `YYYYMMDD` not touching other digits, 1990-2030."""
    for found in NAME_DATE.finditer(name):
        year, month, day = (int(part) for part in found.groups() if part is not None)
        if MIN_YEAR <= year <= MAX_YEAR and valid_date(year, month, day):
            return iso(year, month, day)
    return None


def file_date(row: Row) -> str:
    return embedded_date(row) or name_date(file_name(row.path)) or row.mtime_utc[:10]


# ----- Names (rules 1, 4 and 5) -----


def claimed_ext(name: str) -> str:
    found = CLAIMED_EXT.match(name)
    return found.group(2) if found else ""


def stem(name: str) -> str:
    found = CLAIMED_EXT.match(name)
    return found.group(1) if found else name


def is_junk(name: str) -> bool:
    return name.lower() in JUNK_NAMES or name.startswith("~$") or claimed_ext(name).lower() in JUNK_EXTS


def slug(name: str) -> str:
    """Rule 4: the ASCII, lowercase, copy-marker-free, hyphenated form of a file name's stem."""
    text = unicodedata.normalize("NFKD", stem(name)).encode("ascii", "ignore").decode("ascii").lower()
    while True:
        stripped = COPY_MARKERS.sub("", text)
        if stripped == text:
            break
        text = stripped
    return NOT_SLUG.sub("-", text).strip("-") or EMPTY_SLUG


def target(row: Row) -> str:
    """Where a kept file goes before any collision suffix."""
    date = file_date(row)
    return f"{ORGANIZED}/{CATEGORIES[row.type]}/{date[:4]}/{date}_{slug(file_name(row.path))}.{row.type}"


def with_suffix(base: str, number: int) -> str:
    head, _dot, ext = base.rpartition(".")
    return f"{head}-{number}.{ext}"


def plan(rows: list[Row]) -> Plan:
    """What the rules do with the files under inbox/ (other rows are ignored)."""
    deletes: list[str] = []
    removed = duplicates = 0
    kept: dict[str, Row] = {}
    for row in sorted((row for row in rows if row.path.startswith(INBOX + "/")), key=lambda row: row.path):
        if row.size == 0 or is_junk(file_name(row.path)):
            deletes.append(row.path)
            removed += 1
            continue
        best = kept.get(row.sha256)
        if best is None:
            kept[row.sha256] = row
            continue
        duplicates += 1
        if (row.mtime_utc, row.path) < (best.mtime_utc, best.path):
            deletes.append(best.path)
            kept[row.sha256] = row
        else:
            deletes.append(row.path)
    taken: set[str] = set()
    moves: list[tuple[str, str]] = []
    expected: list[tuple[str, str]] = []
    for row in sorted(kept.values(), key=lambda row: (row.mtime_utc, row.path)):
        base = target(row)
        destination, number = base, 1
        while destination in taken:
            number += 1
            destination = with_suffix(base, number)
        taken.add(destination)
        moves.append((row.path, destination))
        expected.append((row.sha256, destination))
    return Plan(
        moves=tuple(moves),
        deletes=tuple(sorted(deletes)),
        expected=tuple(sorted(expected, key=lambda pair: pair[1])),
        unique=len(kept),
        duplicates=duplicates,
        removed=removed,
    )


def target_problem(path: str) -> str | None:
    """What keeps `path` from being a final path the rules could give, or None."""
    found = TARGET.match(path)
    if not found:
        return "not organized/<category>/<YYYY>/<YYYY-MM-DD>_<slug>.<ext>"
    category, folder, year, month, day, _word, ext = found.groups()
    if CATEGORIES.get(ext) != category:
        return f"a .{ext} file does not belong in {category}"
    if folder != year:
        return "the year folder differs from the date"
    if not valid_date(int(year), int(month), int(day)):
        return "not a real date"
    return None


# ----- Reading a folder -----


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def describe(path: Path, relative: str) -> Row:
    """`path` as one inventory row, `relative` being its path from the folder root."""
    data = path.read_bytes()
    kind = sniff(data)
    name = file_name(relative)
    text = as_text(data) if kind == "md" else None
    return Row(
        path=relative,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        type=kind,
        ext=claimed_ext(name),
        exif=exif_datetime(data) if kind == "jpg" else None,
        png=png_creation_time(data) if kind == "png" else None,
        pdf=pdf_creation_date(data) if kind == "pdf" else None,
        md=frontmatter_date(text) if text is not None else None,
        mtime_utc=utc_stamp(path.stat().st_mtime_ns // 1_000_000_000),
    )


def files_under(root: Path) -> list[Path]:
    """Every regular file under `root` (symlinks left out), sorted by its relative path."""
    found = [path for path in root.rglob("*") if path.is_file() and not path.is_symlink()]
    return sorted(found, key=lambda path: path.relative_to(root).as_posix())


def inventory_rows(root: Path) -> list[Row]:
    """Every file under the task root, as the inventory lists it, sorted by path."""
    return [describe(path, path.relative_to(root).as_posix()) for path in files_under(root)]
