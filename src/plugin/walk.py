"""RULES.md §1 and the facts §2-§4 give each file: which files take part, the limits, and what one file's
bytes and name say about it (type, date, slug, base path, whether it conforms).

Shared, byte for byte, by src/plugin/ and verifier/: it reads files with pathlib only and writes nothing.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .meta import embedded
from .naming import base_path, claimed_ext, conforms, is_hidden, is_junk, name_facts
from .sniff import decoded, sniff

MAX_FILES = 1000
MAX_BYTES = 200 * 1024 * 1024
MAX_FILE = 10 * 1024 * 1024
MAX_DEPTH = 12
MAX_PATH = 300
MAX_ENTRIES = 4900
NAME_SOURCE = "name"
NO_DATE = "none"


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
class Scan:
    """What a folder holds: the files that take part, every existing path, the hidden entries, and
    why the rules refuse it (empty when they do not)."""

    files: list[str]  # relative paths of the files that take part, sorted by code point
    paths: list[str]  # every existing path below the folder (files and folders, hidden ones too)
    hidden: int  # entries the rules leave alone (hidden names and everything below them)
    problems: list[str]


def file_name(path: str) -> str:
    return path.rpartition("/")[2]


def describe(path: str, data: bytes) -> Facts:
    """The facts the rules derive from a file's relative path and bytes alone."""
    name = file_name(path)
    claimed = claimed_ext(name)
    kind = sniff(data, name, claimed)
    junk = is_junk(name)
    text = decoded(data) if kind.type == "md" else None
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


def count_below(folder: Path) -> int:
    """Every entry below `folder`, symlinks counted but never followed."""
    total = 0
    stack = [folder]
    while stack:
        for entry in stack.pop().iterdir():
            total += 1
            if entry.is_dir() and not entry.is_symlink():
                stack.append(entry)
    return total


def scan(root: Path) -> Scan:
    """Walk the folder `root` by RULES §1: hidden names are left alone, junk is not hidden, and a
    symlink or special file anywhere the rules look is a problem."""
    files: list[str] = []
    paths: list[str] = []
    problems: list[str] = []
    hidden = 0
    stack = [(root, "")]
    while stack:
        folder, prefix = stack.pop()
        for entry in sorted(folder.iterdir(), key=lambda item: item.name):
            relative = prefix + entry.name
            paths.append(relative)
            if is_hidden(entry.name):
                hidden += 1 + (count_below(entry) if entry.is_dir() and not entry.is_symlink() else 0)
                continue
            if entry.is_symlink():
                problems.append(f"{relative} is a symlink")
            elif entry.is_dir():
                stack.append((entry, relative + "/"))
            elif entry.is_file():
                files.append(relative)
            else:
                problems.append(f"{relative} is not a regular file")
    files.sort()
    paths.sort()
    return Scan(files=files, paths=paths, hidden=hidden, problems=problems)


def limit_problems(scan: Scan, root: Path, prefix: str) -> list[str]:
    """RULES §1's limits on what takes part. `prefix` is the folder's path in the agent folder, with a
    trailing `/` (empty for the whole agent folder)."""
    problems = []
    if len(scan.files) > MAX_FILES:
        problems.append(f"{len(scan.files)} files take part, more than the {MAX_FILES} one run can plan")
    total = 0
    for relative in scan.files:
        size = root.joinpath(relative).stat().st_size
        total += size
        if size > MAX_FILE:
            problems.append(f"{relative} is {size} bytes, over the 10 MiB a file may be")
        if relative.count("/") > MAX_DEPTH:
            problems.append(f"{relative} is deeper than {MAX_DEPTH} folders")
        if len(prefix + relative) > MAX_PATH:
            problems.append(f"{prefix + relative} is longer than {MAX_PATH} characters")
    if total > MAX_BYTES:
        problems.append(f"the files hold {total} bytes, more than the 200 MiB one run can plan")
    return problems
