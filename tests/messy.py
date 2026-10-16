"""Messy folders, deterministically: the same (seed, profile) always gives the same paths and bytes.

A folder is a dict {path in the agent folder: bytes}; `write_tar` stores one as a reproducible tar (sorted
entries, fixed mtimes, owners and modes), which the scripted harness unpacks into the workspace before a
run. Files come from tests/builders.py, or from the real-file corpus (tests/corpus) when `real` lists
some. The mess: duplicates under the names copying gives them on Windows, macOS, browsers and Drive;
misnamed, upper-case and missing extensions; dates in names (some invalid); NFC and NFD Unicode names;
junk; empty files; hidden folders that must stay untouched; collisions; and, for some profiles, an
organized/ folder from an earlier run with files in place, a gap and files out of place.

Generated names are unique ignoring letter case and Unicode normalization within a folder, and never equal
a folder's name, so a folder unpacks the same on macOS (APFS) and Linux.
"""

from __future__ import annotations

import io
import random
import tarfile
import unicodedata
from pathlib import Path

from builders import DATED, SAMPLES, natural_ext

KINDS = ["jpg", "png", "png-text", "pdf", "docx", "xlsx", "pptx", "odt", "ods", "heic", "avif", "webp", "tiff", "nef", "mp4", "mov", "m4a", "mp3", "wav", "gif", "zip", "jar", "gz", "txt", "md", "csv", "json", "log", "html", "svg", "py", "yaml", "epub", "flac", "ogg", "webm", "mkv", "7z", "rar", "raf", "bin", "avi", "tar", "rtf", "odp"]
WEIGHTS = [14, 6, 3, 9, 5, 3, 2, 2, 1, 3, 2, 2, 1, 1, 3, 2, 1, 2, 1, 2, 2, 1, 1, 5, 4, 3, 3, 2, 2, 2, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
STEMS = {
    "jpg": ["IMG_0042", "DSC00123", "vacation beach", "Photo 2019-07-14 10.22.31", "IMG_20180305_120102", "família", "sunset", "passport scan", "photo"],
    "png": ["Screen Shot 2020-02-29 at 9.15.03 AM", "diagram", "logo", "chart", "wireframe"],
    "pdf": ["invoice", "Invoice #1023", "contract draft", "Résumé – Jürgen Müller", "Tax Return 2020", "scan", "paper", "receipt 20210229"],
    "docx": ["letter", "Meeting notes", "Thesis chapter 3", "CV", "memo"],
    "txt": ["notes", "todo", "naïve café", "Mr. Smith letter", "README"],
    "md": ["README", "journal", "ideas", "CHANGELOG"],
    "csv": ["sales", "contacts", "expenses 2019-13-45", "grades"],
    "py": ["script", "main", "utils", "analysis"],
    "mp4": ["VID_20200101_000001", "clip", "birthday party"],
}
GENERIC = ["file", "untitled", "document", "backup", "export", "data", "Zürich trip", "São Paulo", "Łódź", "日本語メモ", "ＡＢＣ report", "Ñandú", "Ωmega"]
FOLDERS = ["Photos", "Documents", "Downloads", "old stuff", "Desktop backup", "2019", "Work", "Projects", "Mémoire", "misc", "Camera Uploads", "Archive", "Scans", "src", "backup (1)", "New folder", "Taxes", "Школа"]
COPY_NAMES = [
    lambda stem, ext: f"{stem} - Copy{ext}",
    lambda stem, ext: f"{stem} - Copy (2){ext}",
    lambda stem, ext: f"{stem} (1){ext}",
    lambda stem, ext: f"{stem} copy{ext}",
    lambda stem, ext: f"{stem} copy 2{ext}",
    lambda stem, ext: f"Copy of {stem}{ext}",
    lambda stem, ext: f"{stem}{ext.upper()}",
    lambda stem, ext: f"{stem}_copy{ext}",
]
WRONG_EXT = {"jpg": ".png", "heic": ".jpg", "pdf": ".txt", "docx": ".zip", "zip": ".docx", "txt": ".jpg", "svg": ".png", "png": ".jpeg"}
ALTERNATE_EXT = {"jpg": ".jpeg", "html": ".htm", "yaml": ".yml", "md": ".markdown", "tiff": ".tif"}
JUNK = {
    ".DS_Store": b"\x00\x00\x00\x01Bud1" + b"\x00" * 24,
    "Thumbs.db": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 24,
    "desktop.ini": b"[.ShellClassInfo]\r\nIconResource=x\r\n",
    "Icon\r": b"",
}
PROFILES = {"small": 45, "medium": 110, "multirun": 150, "incremental": 25, "edge": 40, "stress": 900}


def key(path: str) -> str:
    return unicodedata.normalize("NFD", unicodedata.normalize("NFD", path).casefold())


class Folder:
    """Paths and bytes being assembled. A new path must not equal an existing file or folder ignoring
    letter case and Unicode normalization, must not need a folder where a file is, and must spell every
    existing folder exactly as it was first spelled."""

    def __init__(self, prefix: str) -> None:
        self.prefix = prefix  # e.g. "Downloads/"
        self.files: dict[str, bytes] = {}
        self.file_keys: set[str] = set()
        self.folders: dict[str, str] = {}  # key -> the folder's spelling

    def free(self, path: str) -> bool:
        full = self.prefix + path
        if key(full) in self.file_keys or key(full) in self.folders:
            return False
        parts = full.split("/")
        for end in range(1, len(parts)):
            ancestor = "/".join(parts[:end])
            if key(ancestor) in self.file_keys or self.folders.get(key(ancestor), ancestor) != ancestor:
                return False
        return True

    def add(self, path: str, data: bytes) -> str | None:
        if not path or not self.free(path):
            return None
        full = self.prefix + path
        self.files[full] = data
        self.file_keys.add(key(full))
        parts = full.split("/")
        for end in range(1, len(parts)):
            self.folders.setdefault(key("/".join(parts[:end])), "/".join(parts[:end]))
        return full


def random_date(rng: random.Random) -> str:
    return f"{rng.randrange(2005, 2025)}-{rng.randrange(1, 13):02d}-{rng.randrange(1, 29):02d}"


def stem_for(rng: random.Random, kind: str) -> str:
    base = rng.choice(STEMS.get(kind, []) + GENERIC)
    roll = rng.random()
    if roll < 0.15:
        base = f"{base} {random_date(rng)}"
    elif roll < 0.22:
        base = f"{random_date(rng).replace('-', '')}_{base}"
    if rng.random() < 0.12:
        base = unicodedata.normalize("NFD", base)
    return base


def ext_for(rng: random.Random, kind: str) -> str:
    natural = "." + natural_ext(kind)
    roll = rng.random()
    if roll < 0.10 and kind in WRONG_EXT:
        return WRONG_EXT[kind]
    if roll < 0.18:
        return natural.upper()
    if roll < 0.24 and kind in ALTERNATE_EXT:
        return ALTERNATE_EXT[kind]
    if roll < 0.28:
        return ""
    return natural


def folder_path(rng: random.Random, depth: int) -> str:
    return "/".join(rng.choice(FOLDERS) for _ in range(rng.randrange(0, depth + 1)))


def joined(folder: str, name: str) -> str:
    return f"{folder}/{name}" if folder else name


def sample(rng: random.Random, kind: str, real: dict[str, list[bytes]] | None) -> bytes:
    pool = (real or {}).get(kind)
    if pool and rng.random() < 0.7:
        return rng.choice(pool)
    date = random_date(rng) if kind in DATED and rng.random() < 0.7 else None
    return SAMPLES[kind](rng.randrange(1 << 30), date)


def messy(seed: int, profile: str = "small", folder: str = "Downloads", real: dict[str, list[bytes]] | None = None) -> dict[str, bytes]:
    """A messy folder `folder` (with a little outside it) for (seed, profile), as {agent-folder path: bytes}."""
    rng = random.Random(f"file-organizer:messy:v2:{seed}:{profile}")
    target = PROFILES[profile]
    prefix = "" if folder == "." else folder + "/"
    made = Folder(prefix)
    depth = 2 if profile in ("small", "edge") else 4
    originals: list[tuple[str, str, bytes]] = []  # (path, kind, bytes) of every base file
    attempts = 0
    while len(made.files) < target * 0.62 and attempts < target * 20:
        attempts += 1
        kind = rng.choices(KINDS, WEIGHTS)[0]
        name = stem_for(rng, kind) + ext_for(rng, kind)
        path = made.add(joined(folder_path(rng, depth), name), sample(rng, kind, real))
        if path:
            originals.append((path, kind, made.files[path]))
    # exact duplicates under the names copying gives them, beside the original or elsewhere
    for path, kind, data in originals:
        if rng.random() < 0.28:
            name = path.rpartition("/")[2]
            stem, dot, ext = name.rpartition(".")
            stem, ext = (stem, dot + ext) if dot and stem else (name, "")
            for _copy in range(rng.choice([1, 1, 2, 3])):
                where = path.rpartition("/")[0][len(prefix) :] if rng.random() < 0.6 else folder_path(rng, depth)
                made.add(joined(where, rng.choice(COPY_NAMES)(stem, ext)), data)
    # near duplicates: the same name and size elsewhere, other bytes
    for path, kind, data in originals:
        if rng.random() < 0.05 and kind in ("txt", "csv", "json", "bin") and len(data) >= 2:
            changed = data[:-2] + bytes([data[-2] ^ 1]) + data[-1:]  # the same size, other bytes
            made.add(joined(folder_path(rng, depth), path.rpartition("/")[2]), changed)
    # collisions: files whose base path is the same (undated READMEs, one photo name)
    for index in range(rng.randrange(2, 5)):
        made.add(joined(folder_path(rng, depth), "README.md" if index % 2 else "notes.txt"), f"# Notes {seed}.{index}\n\n{rng.random()}\n".encode())
    # junk and empty files
    for name, data in JUNK.items():
        if rng.random() < 0.6:
            made.add(joined(folder_path(rng, depth), name), data)
    for path, _kind, _data in originals[: rng.randrange(1, 4)]:
        name = path.rpartition("/")[2]
        made.add(joined(path.rpartition("/")[0][len(prefix) :], "._" + name), b"\x00\x05\x16\x07\x00\x02\x00\x00Mac OS X        ")
    made.add(joined(folder_path(rng, depth), "~$" + "report.docx"), b"\x0fjunk owner file")
    for suffix in (".crdownload", ".part", ".tmp"):
        if rng.random() < 0.5:
            made.add(joined(folder_path(rng, depth), f"download{rng.randrange(99)}{suffix}"), bytes(rng.randrange(256) for _ in range(30)))
    for index in range(rng.randrange(1, 4)):
        made.add(joined(folder_path(rng, depth), f"empty{index}.txt"), b"")
    # hidden: never touched
    made.add(".git/HEAD", b"ref: refs/heads/main\n")
    made.add(".git/config", b"[core]\n\tbare = false\n")
    made.add(".vscode/settings.json", b'{"editor.tabSize": 2}\n')
    made.add(".hidden-note.txt", b"leave me alone\n")
    # outside the folder: never touched either
    files = dict(made.files)
    if prefix:
        files["Notes/keep me.txt"] = b"this file is outside the folder\n"
    return files


def organized_folder(seed: int, folder: str = "Photos", stays: int = 30, new: int = 25) -> dict[str, bytes]:
    """A folder already organized by an earlier run (stays, a gap in a collision sequence, a file out of
    place inside organized/, a copy of a stay outside it), plus new messy files."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from plugin.walk import describe

    rng = random.Random(f"file-organizer:organized:v2:{seed}")
    prefix = "" if folder == "." else folder + "/"
    made = Folder(prefix)
    kept: list[tuple[str, bytes]] = []
    attempts = 0
    while len(kept) < stays and attempts < stays * 50:
        attempts += 1
        kind = rng.choice(["jpg", "pdf", "docx", "md", "png", "mp4"])
        data = SAMPLES[kind](rng.randrange(1 << 30), random_date(rng))
        facts = describe(f"x.{natural_ext(kind)}", data)
        slug = rng.choice(["beach", "invoice", "notes", "report", "trip", "scan", "family"])
        path = facts.base.rpartition("/")[0] + f"/{facts.date}_{slug}.{facts.ext}"
        if rng.random() < 0.15:
            path = path[: -len(facts.ext) - 1] + f"_3.{facts.ext}"  # a gap: _3 without _2
        if made.add(path, data):
            kept.append((prefix + path, data))
    # a file out of place inside organized/: a PNG filed as a jpg
    png = SAMPLES["png"](rng.randrange(1 << 30), "2018-05-06")
    made.add("organized/images/jpg/2018/2018-05-06_misfiled.jpg", png)
    # a copy of a stay outside organized/, under a messy name
    path, data = kept[0]
    made.add("Camera Uploads/IMG_9999.JPG", data)
    rest = messy(seed, "incremental", folder)
    for path, data in rest.items():
        if path.startswith(prefix) and not path[len(prefix) :].startswith(".") and len(made.files) < stays + new + 8:
            made.add(path[len(prefix) :], data)
    files = dict(made.files)
    files.update({path: data for path, data in rest.items() if not path.startswith(prefix)})
    return files


def write_tar(files: dict[str, bytes], destination: Path) -> None:
    """Store `files` as a reproducible tar: sorted, mtime 1,700,000,000, uid/gid 0, modes 0644/0755."""
    buffer = io.BytesIO()
    folders: set[str] = set()
    for path in files:
        parts = path.split("/")
        folders.update("/".join(parts[:end]) for end in range(1, len(parts)))
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name in sorted(folders | set(files)):
            info = tarfile.TarInfo(name)
            info.mtime, info.uid, info.gid, info.uname, info.gname = 1_700_000_000, 0, 0, "", ""
            if name in files:
                info.size, info.mode = len(files[name]), 0o644
                archive.addfile(info, io.BytesIO(files[name]))
            else:
                info.type, info.mode = tarfile.DIRTYPE, 0o755
                archive.addfile(info)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(buffer.getvalue())


def unpack(files: dict[str, bytes], root: Path) -> None:
    """Write `files` under `root` (tests)."""
    for path, data in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
