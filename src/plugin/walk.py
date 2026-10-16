"""RULES.md §1 and the facts §2-§4 give each file: what the agent folder holds, which files take part,
what the rules leave exactly as it was, the limits, and what one file's bytes and name say about it
(type, date, slug, base path, whether it conforms).

Shared, byte for byte, by src/plugin/ and verifier/: it reads files with pathlib only and writes nothing.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .meta import embedded
from .naming import base_path, claimed_ext, conforms, is_hidden, is_junk, name_facts
from .sniff import as_text, sniff

MAX_FILES = 1000
MAX_BYTES = 200 * 1024 * 1024
MAX_FILE = 10 * 1024 * 1024
MAX_DEPTH = 12
MAX_PATH = 300
MAX_ENTRIES = 4900
MAX_AGENT_BYTES = 1024 * 1024 * 1024
STATE_DIR = ".file-organizer"
STATE_FILE = "state.json"
NAME_SOURCE = "name"
NO_DATE = "none"
KIND_BITS, FOLDER_BITS, FILE_BITS, LINK_BITS = 0o170000, 0o040000, 0o100000, 0o120000
OWNER_READ, OWNER_OPEN = 0o400, 0o500
# Where a folder of the walk lies: outside the folder to organize, inside it, inside a hidden folder in
# it, or inside the plugin's own state folder.
OUTSIDE, INSIDE, HIDDEN, STATE = "outside", "inside", "hidden", "state"


@dataclass(frozen=True)
class Facts:
    """One file as the rules see it. `path` is relative to the folder."""

    path: str
    size: int
    sha256: str
    junk: bool
    group: str
    type: str
    ext: str
    date_source: str
    date_raw: str | None
    date: str | None
    slug: str
    base: str | None
    conforming: bool


@dataclass(frozen=True)
class Entry:
    """A file or folder the rules leave exactly as it was; `path` is relative to the agent folder."""

    path: str
    folder: bool
    size: int


@dataclass(frozen=True)
class Scan:
    """What the agent folder holds, as RULES §1 sees it, and why the rules refuse it (`problems`)."""

    prefix: str  # the folder's path in the agent folder, as listed ("" for the whole agent folder)
    files: dict[str, int]  # the files that take part: path relative to the folder -> size, by path
    folders: list[str]  # the folders inside the folder that are not hidden, relative to it, sorted
    empty: list[str]  # those of them that hold no file and no hidden entry: a run removes them first
    kept: list[Entry]  # hidden entries inside the folder and every entry outside it, sorted by path
    problems: list[str]
    total: int  # bytes of every file in the agent folder, the run state aside


def file_name(path: str) -> str:
    return path.rpartition("/")[2]


def describe(path: str, data: bytes) -> Facts:
    """The facts the rules derive from a file's relative path and bytes alone."""
    name = file_name(path)
    claimed = claimed_ext(name)
    kind = sniff(data, name, claimed)
    junk = is_junk(name)
    text = as_text(data, claimed) if kind.type == "md" else None
    named_date, slug = name_facts(name, kind.ext)
    found = embedded(kind.type, kind.ext, data, text)
    if found:
        source, raw, date = found
    elif named_date:
        source, raw, date = NAME_SOURCE, name, named_date
    else:
        source, raw, date = NO_DATE, None, None
    base = None if junk or not data else base_path(kind.group, kind.type, kind.ext, date, slug)
    return Facts(
        path=path,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        junk=junk,
        group=kind.group,
        type=kind.type,
        ext=kind.ext,
        date_source=source,
        date_raw=raw,
        date=date,
        slug=slug,
        base=base,
        conforming=base is not None and conforms(path, base, kind.ext),
    )


def entry_kind(entry: Path) -> str:
    """folder, file, link, special, or locked: a file its owner may not read, or a folder its owner may not open."""
    mode = entry.lstat().st_mode
    kind = mode & KIND_BITS
    if kind == LINK_BITS:
        return "link"
    if kind == FOLDER_BITS:
        return "folder" if mode & OWNER_OPEN == OWNER_OPEN else "locked"
    if kind == FILE_BITS:
        return "file" if mode & OWNER_READ else "locked"
    return "special"


def inside(path: str, prefix: str) -> bool:
    """Whether a path relative to the agent folder lies inside the folder `prefix` ("" for the whole)."""
    return not prefix or path.startswith(prefix + "/")


def within(path: str, prefix: str) -> str:
    """A path inside the folder `prefix`, relative to the folder."""
    return path[len(prefix) + 1 :] if prefix else path


def parents(path: str) -> list[str]:
    parts = path.split("/")
    return ["/".join(parts[:end]) for end in range(1, len(parts))]


def scan(workspace: Path, root: Path) -> Scan:
    """Walk the whole agent folder `workspace` by RULES §1. `root` is the folder to organize in it."""
    prefix = "" if root == workspace else root.relative_to(workspace).as_posix()
    files: dict[str, int] = {}
    folders: list[str] = []
    kept: list[Entry] = []
    problems: list[str] = []
    total = 0
    stack = [(workspace, "", OUTSIDE if prefix else INSIDE)]
    while stack:
        folder, at, place = stack.pop()
        try:
            listed = sorted(folder.iterdir(), key=lambda item: item.name)
        except OSError:
            problems.append(f"{at.rstrip('/') or '.'} cannot be read")
            continue
        for entry in listed:
            path = at + entry.name
            try:
                kind = entry_kind(entry)
                size = entry.lstat().st_size if kind == "file" else 0
            except OSError:
                kind, size = "locked", 0
            if kind == "link":
                problems.append(f"{path} is a symlink")
                continue
            if kind == "special":
                problems.append(f"{path} is not a regular file or folder")
                continue
            if kind == "locked":
                problems.append(f"{path} cannot be read")
                continue
            if not at and entry.name == STATE_DIR:
                if kind == "folder":
                    stack.append((entry, path + "/", STATE))
                else:
                    problems.append(f"{path} is not a folder, but the plugin keeps its run state there")
                continue
            if place == STATE and at == STATE_DIR + "/" and entry.name == STATE_FILE:
                continue
            total += size
            if place == OUTSIDE and path == prefix:
                stack.append((entry, path + "/", INSIDE))
                continue
            if place == INSIDE and not is_hidden(entry.name, kind == "folder"):
                if kind == "folder":
                    folders.append(within(path, prefix))
                    stack.append((entry, path + "/", INSIDE))
                else:
                    files[within(path, prefix)] = size
                continue
            kept.append(Entry(path, kind == "folder", size))
            if kind == "folder":
                stack.append((entry, path + "/", HIDDEN if place == INSIDE else place))
    holding = {parent for relative in files for parent in parents(relative)}
    holding.update(parent for entry in kept if inside(entry.path, prefix) for parent in parents(within(entry.path, prefix)))
    folders.sort()
    return Scan(
        prefix=prefix,
        files=dict(sorted(files.items())),
        folders=folders,
        empty=[folder for folder in folders if folder not in holding],
        kept=sorted(kept, key=lambda entry: entry.path),
        problems=sorted(problems),
        total=total,
    )


def limit_problems(scanned: Scan) -> list[str]:
    """RULES §1's limits on what takes part and on the whole agent folder."""
    problems = []
    if len(scanned.files) > MAX_FILES:
        problems.append(f"{len(scanned.files)} files take part, more than the {MAX_FILES} one run can plan")
    total = 0
    for relative, size in scanned.files.items():
        total += size
        path = f"{scanned.prefix}/{relative}" if scanned.prefix else relative
        if size > MAX_FILE:
            problems.append(f"{path} is {size} bytes, over the 10 MiB a file may be")
        if relative.count("/") > MAX_DEPTH:
            problems.append(f"{path} is deeper than {MAX_DEPTH} folders")
        if len(path) > MAX_PATH:
            problems.append(f"{path} is longer than {MAX_PATH} characters")
    if total > MAX_BYTES:
        problems.append(f"the files hold {total} bytes, more than the 200 MiB one run can plan")
    if scanned.total > MAX_AGENT_BYTES:
        problems.append(f"your agent folder holds {scanned.total} bytes, more than the 1 GiB the rules read to check a run")
    return problems


def file_sha256(path: Path) -> str:
    """A file's SHA-256, read in pieces; OSError when it cannot be read."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def kept_digests(workspace: Path, kept: list[Entry]) -> tuple[dict[str, str], list[str]]:
    """The SHA-256 of every file among `kept`, and the ones that cannot be read."""
    digests: dict[str, str] = {}
    problems: list[str] = []
    for entry in kept:
        if entry.folder:
            continue
        try:
            digests[entry.path] = file_sha256(workspace / entry.path)
        except OSError:
            problems.append(f"{entry.path} cannot be read")
    return digests, problems


def count_below(folder: Path) -> int:
    """Every entry below `folder`, symlinks counted but never followed; a folder that cannot be listed counts alone."""
    total = 0
    stack = [folder]
    while stack:
        try:
            listed = list(stack.pop().iterdir())
        except OSError:
            continue
        for entry in listed:
            total += 1
            try:
                if entry_kind(entry) == "folder":
                    stack.append(entry)
            except OSError:
                continue
    return total
