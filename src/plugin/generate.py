"""The messy folder: the same seed and size give the same files, bytes, names and mtimes on any machine.

Every choice comes from one random.Random seeded from (seed, size), drawn in one fixed order, so
nothing depends on dict or directory order. Every file's bytes are built here: JPEGs from the
shipped fixtures with an EXIF segment made by Pillow, PNGs chunk by chunk, minimal PDFs, stored
(uncompressed) DOCX and ZIP archives with fixed dates, and text files from a small vocabulary.
"""

from __future__ import annotations

import io
import json
import os
import random
import unicodedata
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from plugin import rules

VERSION = "v1"
FIXTURES = [path.read_bytes() for path in sorted(Path(__file__).with_name("data").joinpath("jpeg").glob("*.jpg"))]
# Modification times: 2016-01-01 to 2025-09-30, whole seconds, UTC.
EPOCH_START, EPOCH_END = 1451606400, 1759190400
# Embedded dates: 2010 to 2024.
META_START, META_END = 1262304000, 1735689599
# What share of the files is what, as the plan sets it.
SHARES = {"junk": 0.06, "empty": 0.03, "near_pairs": 0.04, "collisions": 0.03, "duplicates": 0.25}

KINDS = ["jpg", "png", "pdf", "docx", "zip", "svg", "html", "py", "json", "log", "md", "csv", "txt", "bin"]
WEIGHTS = [15, 10, 12, 6, 4, 4, 5, 6, 7, 6, 7, 6, 8, 4]
# Kinds a near-duplicate pair (same name and size, different bytes) is made of.
NEAR_KINDS = ["txt", "csv", "json", "log", "md", "html", "svg", "py", "png", "jpg", "pdf", "bin", "docx"]
ALTERNATE = {"jpg": "jpeg", "html": "htm"}
WRONG_EXTS = ["jpg", "png", "pdf", "docx", "zip", "txt", "md", "csv", "json", "xlsx", "doc", "dat", "jpeg", "htm", "log"]
STEMS = {
    "jpg": ["IMG_0042", "DSC00123", "vacation beach", "Photo 2019-07-14 10.22.31", "Screenshot 2021-03-04 at 10.22.31", "família", "sunset", "birthday party", "IMG_20180305_120102", "passport scan"],
    "png": ["screenshot", "diagram", "logo", "chart", "Screen Shot 2020-02-29 at 9.15.03 AM", "icon", "wireframe", "map"],
    "pdf": ["invoice", "Invoice #1023", "contract draft", "Résumé – Jürgen Müller", "Tax Return 2020", "scan", "manual", "paper", "receipt"],
    "docx": ["letter", "Meeting notes", "proposal", "Thesis chapter 3", "CV", "memo", "agenda"],
    "zip": ["backup", "photos archive", "project files", "src", "exports"],
    "svg": ["logo", "icon", "diagram", "map", "banner"],
    "html": ["index", "page", "newsletter", "saved article", "bookmarks"],
    "py": ["script", "main", "utils", "analysis", "scraper", "train"],
    "json": ["config", "data", "settings", "export", "package", "manifest"],
    "csv": ["sales", "contacts", "expenses", "grades", "inventory", "timesheet"],
    "log": ["server", "app", "build", "error", "access", "sync"],
    "md": ["README", "notes", "TODO", "journal", "ideas", "CHANGELOG"],
    "txt": ["notes", "todo", "readme", "quotes", "shopping list", "naïve café", "Mr. Smith letter"],
    "bin": ["firmware", "blob", "cache", "unknown", "dump"],
}
UNICODE_WORDS = ["Zürich", "São Paulo", "Łódź", "Ωmega", "日本語メモ", "ＡＢＣ", "ﬁnal", "Mémoire", "Jürgen Müller", "Ñandú"]
MARKERS = [" (draft)", " final", " v2", "_old", " - notes", " (2)", "-FINAL", "_v3"]
INVALID_DATES = ["2019-13-45", "20191345", "1985-06-01", "2031-05-06", "2019-02-30", "20210229"]
DIR_NAMES = [
    "Photos", "Documents", "Downloads", "old stuff", "Desktop backup", "2019", "Work", "Projects", "Alpha", "Mémoire",
    "misc", "tmp", "Camera Uploads", "Archive", "2018", "Scans", "Notes", "src", "backup (1)", "Untitled Folder",
    "New folder", "code", "Family", "Taxes", "Receipts", "to sort", "Inbox old", "Школа",
]
# A small folder stays shallow with short folder names, so its whole plan fits one apply_plan
# call within a hosted reply (2048 tokens); medium and large use the full pool and depth 4.
SHORT_DIR_NAMES = ["Photos", "Docs", "Work", "old", "tmp", "misc", "2019", "Scans", "Notes", "src", "Taxes", "New folder", "Camera", "backup"]
DIR_LIMITS = {"small": (8, 10, 2), "medium": (10, 18, 4), "large": (12, 25, 4)}  # least, most, deepest
WORDS = [
    "alpha", "budget", "contract", "draft", "export", "family", "garden", "holiday", "invoice", "journal", "kitchen",
    "lecture", "meeting", "notes", "offer", "plan", "quarter", "report", "summary", "travel", "update", "vacation",
    "workshop", "review", "ledger", "sketch", "orchard", "harbor", "lantern", "meadow",
]
DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)
RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
    "</Relationships>"
)


@dataclass
class Spec:
    """One file to write: its path under the task root, its bytes, its mtime (whole seconds, UTC)
    and the kind of content it holds."""

    path: str
    data: bytes
    mtime: int
    kind: str


@dataclass
class Made:
    """A base file and what it was made from, for copies and collisions."""

    spec: Spec
    kind: str
    stem: str
    ext: str  # the claimed extension with its dot, or ""
    meta: dict[str, str | None]
    draw: int  # the sub-generator seed its content came from


# ----- Bytes of each kind -----


def jpeg_bytes(fixture: bytes, exif: str | None, comment: str) -> bytes:
    """A fixture JPEG with an APP1 Exif segment (DateTimeOriginal, through Pillow) and a COM segment."""
    segments = b""
    if exif is not None:
        tags = Image.Exif()
        tags.get_ifd(0x8769)[0x9003] = exif
        blob = tags.tobytes()
        segments += b"\xff\xe1" + (len(blob) + 2).to_bytes(2, "big") + blob
    text = comment.encode("ascii")
    segments += b"\xff\xfe" + (len(text) + 2).to_bytes(2, "big") + text
    return fixture[:2] + segments + fixture[2:]


def png_chunk(kind: bytes, body: bytes) -> bytes:
    return len(body).to_bytes(4, "big") + kind + body + zlib.crc32(kind + body).to_bytes(4, "big")


def png_bytes(width: int, height: int, color: tuple[int, int, int], creation: str | None, comment: str) -> bytes:
    """An RGB PNG, chunk by chunk: IHDR, tEXt (Creation Time, Comment), IDAT (zlib level 9), IEND."""
    rows = b"".join(b"\x00" + bytes((color[0], (color[1] + 7 * y) % 256, color[2])) * width for y in range(height))
    chunks = [png_chunk(b"IHDR", width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, 2, 0, 0, 0]))]
    if creation is not None:
        chunks.append(png_chunk(b"tEXt", b"Creation Time\x00" + creation.encode("latin-1")))
    chunks.append(png_chunk(b"tEXt", b"Comment\x00" + comment.encode("latin-1")))
    chunks.append(png_chunk(b"IDAT", zlib.compress(rows, 9)))
    chunks.append(png_chunk(b"IEND", b""))
    return b"\x89PNG\r\n\x1a\n" + b"".join(chunks)


def pdf_bytes(title: str, text: str, creation: str | None) -> bytes:
    """A one-page PDF with a correct xref table and an Info dictionary."""
    content = f"BT /F1 12 Tf 20 50 Td ({text}) Tj ET".encode("latin-1")
    info = f"<< /Title ({title})" + (f" /CreationDate ({creation})" if creation else "") + " >>"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 240 120] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        info.encode("latin-1"),
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info 6 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def zip_bytes(entries: list[tuple[str, bytes]]) -> bytes:
    """A stored (uncompressed) zip with fixed entry dates, so its bytes depend on its entries only."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        for name, data in entries:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
    return buffer.getvalue()


def docx_bytes(text: str) -> bytes:
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    )
    return zip_bytes([("[Content_Types].xml", CONTENT_TYPES.encode()), ("_rels/.rels", RELS.encode()), ("word/document.xml", document.encode())])


def rfc1123(seconds: int) -> str:
    stamp = rules.utc_stamp(seconds)
    day = DAYS[(seconds // 86400 + 4) % 7]
    return f"{day}, {stamp[8:10]} {MONTHS[int(stamp[5:7]) - 1]} {stamp[:4]} {stamp[11:19]} GMT"


def sentence(sub: random.Random, *, commas: bool = False) -> str:
    words = [sub.choice(WORDS) for _ in range(sub.randint(5, 11))]
    if commas and len(words) > 4:
        words[2] += ","
    return " ".join(words).capitalize() + "."


def title(sub: random.Random) -> str:
    return " ".join(sub.choice(WORDS) for _ in range(2)).title()


def content(kind: str, ident: str, meta: dict[str, str | None], draw: int) -> bytes:
    """The bytes of a file of `kind`, unique through `ident` (fixed width), varied through `draw`:
    two files built from the same `draw` and `meta` differ only where `ident` appears."""
    sub = random.Random(draw)
    head = title(sub)
    if kind == "jpg":
        return jpeg_bytes(sub.choice(FIXTURES), meta.get("exif"), ident)
    if kind == "png":
        return png_bytes(sub.randint(2, 8), sub.randint(2, 8), (sub.randint(0, 255), sub.randint(0, 255), sub.randint(0, 255)), meta.get("png"), ident)
    if kind == "pdf":
        return pdf_bytes(head, f"{sentence(sub)} {ident}", meta.get("pdf"))
    if kind == "docx":
        return docx_bytes(f"{head}. {sentence(sub)} {ident}")
    if kind == "zip":
        return zip_bytes([("notes.txt", f"{head}\n{sentence(sub)}\n{ident}\n".encode()), ("data/values.csv", f"key,value\na,{sub.randint(1, 99)}\nb,{ident}\n".encode())])
    if kind == "svg":
        declaration = '<?xml version="1.0" encoding="UTF-8"?>\n' if sub.random() < 0.5 else ""
        color = f"#{sub.randint(0, 0xFFFFFF):06x}"
        return f'{declaration}<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">\n  <rect width="64" height="64" fill="{color}"/>\n  <text x="4" y="40">{ident}</text>\n</svg>\n'.encode()
    if kind == "html":
        doctype = "<!DOCTYPE html>\n" if sub.random() < 0.7 else ""
        return f'{doctype}<html lang="en">\n<head><meta charset="utf-8"><title>{head}</title></head>\n<body><h1>{head}</h1><p>{sentence(sub, commas=True)} {ident}</p></body>\n</html>\n'.encode()
    if kind == "py":
        return f'#!/usr/bin/env python3\n"""{head}."""\n\nIDENT = "{ident}"\n\n\ndef main():\n    print("{sentence(sub)}", IDENT)\n\n\nif __name__ == "__main__":\n    main()\n'.encode()
    if kind == "json":
        record = {"id": ident, "name": head, "tags": [sub.choice(WORDS) for _ in range(3)], "count": sub.randint(1, 500)}
        return (json.dumps([record, {"id": "x", "name": sentence(sub)}] if sub.random() < 0.3 else record, indent=2) + "\n").encode()
    if kind == "csv":
        lines = ["id,name,amount,note"] + [f"{index},{sub.choice(WORDS)},{sub.randint(1, 999)},{sub.choice(WORDS)}" for index in range(sub.randint(3, 8))]
        lines.append(f"{ident},{sub.choice(WORDS)},{sub.randint(1, 999)},end")
        return ("\n".join(lines) + "\n").encode()
    if kind == "log":
        start = sub.randint(META_START, META_END)
        space = sub.random() < 0.5
        lines = []
        for index in range(sub.randint(4, 9)):
            stamp = rules.utc_stamp(start + 61 * index)
            stamp = stamp[:10] + " " + stamp[11:19] if space else stamp
            lines.append(f"{stamp} {'INFO' if index % 3 else 'WARN'} {sentence(sub, commas=True)}")
        lines.append(f"{rules.utc_stamp(start + 999)} INFO run {ident} done")
        return ("\n".join(lines) + "\n").encode()
    if kind == "md":
        front = ""
        if meta.get("md") is not None:
            front = f"---\ntitle: {head}\ndate: {meta['md']}\ntags: [{sub.choice(WORDS)}, {sub.choice(WORDS)}]\n---\n"
        elif sub.random() < 0.2:
            front = f"---\ntitle: {head}\n---\n"
        return f"{front}# {head}\n\n{sentence(sub, commas=True)}\n\n- {sentence(sub)}\n- {ident}\n".encode()
    if kind == "txt":
        return f"{head}\n\n{sentence(sub)}\n{sentence(sub)}\n{ident}\n".encode()
    if kind == "bin":
        return b"\x00\xff" + ident.encode() + sub.randbytes(sub.randint(40, 300))
    raise ValueError(f"no content of kind {kind}")


# ----- The composition -----


def make_dirs(rng: random.Random, size: str) -> tuple[list[str], list[str]]:
    """The folders under inbox (paths relative to it; "" is inbox itself) within DIR_LIMITS for the
    size, and those files may go in (a few leaves stay empty)."""
    least, most, deepest = DIR_LIMITS[size]
    names = SHORT_DIR_NAMES if size == "small" else DIR_NAMES
    count = rng.randint(least, most)
    dirs = [""]
    while len(dirs) < count + 1:
        parent = rng.choice([folder for folder in dirs if folder == "" or folder.count("/") < deepest - 1])
        options = [name for name in names if f"{parent}/{name}".lstrip("/") not in dirs]
        if not options:
            continue
        dirs.append(f"{parent}/{rng.choice(options)}".lstrip("/"))
    leaves = [folder for folder in dirs[1:] if not any(other.startswith(folder + "/") for other in dirs)]
    empty = set(rng.sample(leaves, k=min(len(leaves), rng.randint(1, 3))))
    return dirs, [folder for folder in dirs if folder not in empty]


class Maker:
    """Builds the specs in a fixed order from one generator."""

    def __init__(self, rng: random.Random, dirs: list[str], usable: list[str]) -> None:
        self.rng = rng
        self.usable = usable
        self.specs: list[Spec] = []
        # Every folder counts as taken, so no file is ever named like a folder beside it.
        self.used: set[str] = {self.key(f"{rules.INBOX}/{folder}") for folder in dirs if folder}
        self.mtimes: set[int] = set()
        self.counter = 0

    @staticmethod
    def key(path: str) -> str:
        """How one path is told from another: case- and normalization-insensitively, so the tree is
        the same on a filesystem that folds them (APFS) and on one that does not (ext4)."""
        return unicodedata.normalize("NFC", path).casefold()

    def ident(self) -> str:
        self.counter += 1
        return f"id{self.counter:05d}"

    def fresh_mtime(self, low: int = EPOCH_START, high: int = EPOCH_END) -> int:
        low, high = max(low, EPOCH_START), min(high, EPOCH_END)
        if low > high:
            low, high = EPOCH_START, EPOCH_END
        for _attempt in range(100):
            stamp = self.rng.randint(low, high)
            if stamp not in self.mtimes:
                break
        self.mtimes.add(stamp)
        return stamp

    def place(self, name: str, folder: str | None = None) -> str:
        """A free path for `name`: in `folder` (else a random one), then any other, then numbered."""
        first = self.rng.choice(self.usable) if folder is None else folder
        for candidate in [first, *self.usable]:
            path = f"{rules.INBOX}/{candidate}/{name}".replace("//", "/")
            if self.key(path) not in self.used:
                self.used.add(self.key(path))
                return path
        base, dot, ext = name.rpartition(".")
        for number in range(2, 10_000):
            numbered = f"{base} {number}.{ext}" if dot and base else f"{name} {number}"
            path = f"{rules.INBOX}/{first}/{numbered}".replace("//", "/")
            if self.key(path) not in self.used:
                self.used.add(self.key(path))
                return path
        raise RuntimeError("no free path")

    def add(self, name: str, data: bytes, kind: str, *, folder: str | None = None, mtime: int | None = None) -> Spec:
        spec = Spec(path=self.place(name, folder), data=data, mtime=self.fresh_mtime() if mtime is None else mtime, kind=kind)
        self.specs.append(spec)
        return spec

    # --- names and metadata ---

    def date_token(self) -> str:
        if self.rng.random() < 0.3:
            return self.rng.choice(INVALID_DATES)
        stamp = rules.utc_stamp(self.rng.randint(META_START, META_END))[:10]
        return stamp if self.rng.random() < 0.6 else stamp.replace("-", "")

    def decorate(self, stem: str) -> str:
        roll = self.rng.random()
        if roll < 0.1:
            stem = self.rng.choice(UNICODE_WORDS)
        elif roll < 0.22:
            stem = f"{stem} {self.rng.choice(UNICODE_WORDS)}"
        if self.rng.random() < 0.4:
            token = self.date_token()
            stem = self.rng.choice([f"{stem} {token}", f"{stem}_{token}", f"{token} {stem}", f"{stem}-{token}"])
        if self.rng.random() < 0.15:
            stem += self.rng.choice(MARKERS)
        return stem

    def extension(self, kind: str) -> str:
        roll = self.rng.random()
        if roll < 0.68:
            return f".{kind}"
        if roll < 0.76:
            return f".{kind.upper()}"
        if roll < 0.81:
            return f".{ALTERNATE.get(kind, kind)}"
        if roll < 0.93:
            return "." + self.rng.choice([ext for ext in WRONG_EXTS if ext not in (kind, ALTERNATE.get(kind))])
        return ""

    def metadata(self, kind: str) -> dict[str, str | None]:
        meta: dict[str, str | None] = {"exif": None, "png": None, "pdf": None, "md": None}
        seconds = self.rng.randint(META_START, META_END)
        stamp = rules.utc_stamp(seconds)
        roll = self.rng.random()
        if kind == "jpg" and roll < 0.65:
            meta["exif"] = f"{stamp[:10].replace('-', ':')} {stamp[11:19]}"
        elif kind == "png" and roll < 0.6:
            meta["png"] = stamp if self.rng.random() < 0.5 else rfc1123(seconds)
        elif kind == "pdf" and roll < 0.65:
            compact = stamp[:10].replace("-", "") + stamp[11:19].replace(":", "")
            meta["pdf"] = self.rng.choice([f"D:{compact}Z", f"D:{compact}+02'00'", f"D:{compact[:8]}"])
        elif kind == "md" and roll < 0.55:
            day = stamp[:10]
            meta["md"] = self.rng.choice([day, f'"{day}"', f"'{day}'", stamp, f"{day} 10:22", "14 July 2019", "2019-13-01"][: 7 if self.rng.random() < 0.15 else 5])
        return meta

    # --- the files ---

    def base_file(self) -> Made:
        kind = self.rng.choices(KINDS, WEIGHTS)[0]
        stem = self.decorate(self.rng.choice(STEMS[kind]))
        ext = self.extension(kind)
        meta = self.metadata(kind)
        draw = self.rng.getrandbits(64)
        spec = self.add(stem + ext, content(kind, self.ident(), meta, draw), kind)
        return Made(spec=spec, kind=kind, stem=stem, ext=ext, meta=meta, draw=draw)

    def near_pair(self) -> None:
        """Two files with the same name and size and different bytes, in two folders."""
        kind = self.rng.choice(NEAR_KINDS)
        name = self.decorate(self.rng.choice(STEMS[kind])) + self.extension(kind)
        meta = self.metadata(kind)
        draw = self.rng.getrandbits(64)
        folders = self.rng.sample(self.usable, k=min(2, len(self.usable)))
        first = self.add(name, content(kind, self.ident(), meta, draw), kind, folder=folders[0])
        second = content(kind, self.ident(), meta, draw)
        assert len(second) == len(first.data) and second != first.data
        self.add(name, second, kind, folder=folders[-1])

    def collision(self, made: Made, tie: bool) -> None:
        """A different file that lands on the same final name as `made`: same type, date and slug.
        Its path sorts before `made`'s, and its mtime is later (or, with `tie`, the same), so naming
        by path order gets the pair the wrong way round."""
        spec = made.spec
        if made.meta.get("exif") or made.meta.get("png") or made.meta.get("pdf") or made.meta.get("md"):
            meta = dict(made.meta)
        elif rules.name_date(rules.file_name(spec.path)):
            meta = self.metadata("txt")  # no embedded date: the shared name date decides
        else:
            meta = self.metadata("txt")
        folder = spec.path[len(rules.INBOX) + 1 :].rpartition("/")[0]
        variants = [f"{made.stem} (1){made.ext}", f"{made.stem} - Copy{made.ext}", f"{made.stem}_copy{made.ext}", f"Copy of {made.stem}{made.ext}"]
        name = next((variant for variant in variants if f"{rules.INBOX}/{folder}/{variant}".replace("//", "/") < spec.path), variants[0])
        if tie:
            mtime = spec.mtime
        elif made.meta.get("exif") or made.meta.get("png") or made.meta.get("pdf") or made.meta.get("md") or rules.name_date(rules.file_name(spec.path)):
            mtime = self.fresh_mtime(spec.mtime + 1, EPOCH_END)
        else:
            day_end = (spec.mtime // 86400 + 1) * 86400 - 1
            mtime = self.fresh_mtime(spec.mtime + 1, day_end) if spec.mtime < day_end else spec.mtime
        self.add(name, content(made.kind, self.ident(), meta, self.rng.getrandbits(64)), made.kind, folder=folder, mtime=mtime)

    def copies(self, made: Made, count: int, tie_first: bool) -> None:
        """`count` exact copies of `made` under other names and folders, some older than it."""
        stem, ext, kind = made.stem, made.ext, made.kind
        wrong = "." + self.rng.choice([one for one in WRONG_EXTS if one not in (kind, ALTERNATE.get(kind))])
        variants = [
            f"Copy of {stem}{ext}", f"{stem} (1){ext}", f"{stem} (2){ext}", f"{stem} - Copy{ext}", f"{stem}_copy{ext}",
            f"{stem}-final{ext}", f"{stem}_v2{ext}", f"{stem}{ext.upper()}", f"{stem}{wrong}", stem, f"{stem} - copy (2){ext}", f"{stem}{ext}",
        ]
        for index in range(count):
            name = self.rng.choice(variants)
            if index == 0 and tie_first:
                mtime = made.spec.mtime
            elif self.rng.random() < 0.4:
                mtime = self.fresh_mtime(EPOCH_START, made.spec.mtime - 1)
            else:
                mtime = self.fresh_mtime(made.spec.mtime + 1, EPOCH_END)
            self.add(name, made.spec.data, kind, mtime=mtime)

    def junk(self, index: int) -> None:
        stem = self.rng.choice(WORDS)
        choices = [
            (".DS_Store", b"\x00\x00\x00\x01Bud1\x00" + self.rng.randbytes(40), "bin"),
            (f"{stem}.tmp", content("jpg", self.ident(), {"exif": None}, self.rng.getrandbits(64)), "jpg"),
            ("Thumbs.db", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + self.rng.randbytes(40), "bin"),
            ("desktop.ini", b"[.ShellClassInfo]\r\nIconResource=C:\\WINDOWS\\System32\\SHELL32.dll,3\r\n", "txt"),
            (f"~${stem}.docx", b"\x00\x00" + self.rng.randbytes(20), "bin"),
            (f"{stem} download.part", b"\x00\x01" + self.rng.randbytes(60), "bin"),
            ("thumbs.DB", b"\xd0\xcf\x11\xe0" + self.rng.randbytes(30), "bin"),
            (f"{stem}.TMP", f"temporary {self.ident()}\n".encode(), "txt"),
        ]
        name, data, kind = choices[index % len(choices)]
        self.add(name, data, kind)

    def empty(self) -> None:
        kind = self.rng.choice(KINDS)
        self.add(self.rng.choice(STEMS[kind]) + self.extension(kind), b"", kind)


def build(seed: int, size: str) -> tuple[list[Spec], list[str]]:
    """Every file of the messy folder for (seed, size), and its folders (paths under inbox)."""
    rng = random.Random(f"file-organizer:{VERSION}:{seed}:{size}")
    total = rules.COUNTS[size]
    n_junk, n_empty = round(SHARES["junk"] * total), round(SHARES["empty"] * total)
    n_near, n_collide, n_dup = round(SHARES["near_pairs"] * total), round(SHARES["collisions"] * total), round(SHARES["duplicates"] * total)
    n_base = total - n_junk - n_empty - 2 * n_near - n_collide - n_dup
    dirs, usable = make_dirs(rng, size)
    maker = Maker(rng, dirs, usable)
    base = [maker.base_file() for _ in range(n_base)]
    for _ in range(n_near):
        maker.near_pair()
    targets = rng.sample(base, k=n_collide)
    for index, made in enumerate(targets):
        maker.collision(made, tie=index == 0)
    originals = [made for made in base if made not in targets]
    rng.shuffle(originals)
    remaining, group = n_dup, 0
    while remaining > 0:
        count = min(remaining, rng.randint(1, 3))
        maker.copies(originals[group % len(originals)], count, tie_first=group == 0)
        remaining -= count
        group += 1
    for index in range(n_junk):
        maker.junk(index)
    for _ in range(n_empty):
        maker.empty()
    assert len(maker.specs) == total
    return maker.specs, dirs


def generate(root: Path, seed: int, size: str) -> tuple[int, int]:
    """Write the messy folder under `root`/inbox; how many files and folders it holds."""
    specs, dirs = build(seed, size)
    inbox = root / rules.INBOX
    for folder in dirs:
        (inbox / folder).mkdir(parents=True, exist_ok=True)
    for spec in sorted(specs, key=lambda spec: spec.path):
        path = root / spec.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(spec.data)
    for spec in specs:
        os.utime(root / spec.path, ns=(spec.mtime * 1_000_000_000, spec.mtime * 1_000_000_000))
    return len(specs), len(dirs) - 1
