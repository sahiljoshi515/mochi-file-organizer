"""A whole folder under the rules: which folder the task names, what the rules plan for it, what they
leave exactly as it was, and every reason RULES.md §1 refuses it (symlinks, unreadable entries, limits,
case conflicts, the 5,000 entries RUSH Lab saves).

Shared, byte for byte, by src/plugin/ and verifier/: the tools refuse a folder whose layout is `refused`,
and the verifier re-derives the same plan with `look` to check the answer key and the survey.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .naming import ORGANIZED, path_key
from .plan import DELETE, MOVE, Step, hash_length, ordered, plan
from .walk import (
    MAX_ENTRIES,
    STATE_DIR,
    Entry,
    Facts,
    Scan,
    describe,
    entry_kind,
    inside,
    kept_digests,
    limit_problems,
    parents,
    scan,
    within,
)

FOLDER_LIMIT = 100
FOLDER_PART = re.compile(r"[^/\\\x00]+")
SHOWN_PROBLEMS = 6
SAVED_ENTRIES = 5000


@dataclass(frozen=True)
class Layout:
    folder: str
    prefix: str  # the folder's path in the agent folder, as listed ("" for the whole agent folder)
    facts: list[Facts]  # in the rules' order: facts[i] is file i
    steps: list[Step]
    taken: list[str]
    kept: list[Entry]  # what the run leaves exactly as it was
    digests: dict[str, str]  # the SHA-256 of every kept file, when look read them
    entries_after: int
    hash_length: int
    refused: str | None  # why the rules refuse the folder, or None


def folder_problem(folder: str) -> str | None:
    """What keeps `folder` from naming a folder inside the agent folder, or None."""
    if folder == ".":
        return None
    if not folder or len(folder) > FOLDER_LIMIT:
        return f"folder must be . or a path of 1 to {FOLDER_LIMIT} characters"
    for part in folder.split("/"):
        if not FOLDER_PART.fullmatch(part) or part in (".", ".."):
            return "folder must be a relative path like Downloads or Photos/2019, with / between folders"
        if part.startswith("."):
            return f"{folder} is hidden: the rules leave hidden folders alone"
        if part.lower() == ORGANIZED:
            return f"{folder} is inside an organized/ folder: pass the folder that holds organized/"
    return None


def label(folder: str) -> str:
    return "your File Organizer folder" if folder == "." else folder


def kind_of(path: Path) -> str:
    try:
        return entry_kind(path)
    except OSError:
        return "locked"


def top_level(workspace: Path) -> str:
    try:
        listed = list(workspace.iterdir())
    except OSError:
        listed = []
    names = sorted(entry.name + "/" for entry in listed if not entry.name.startswith(".") and kind_of(entry) == "folder")
    if not names:
        return "no folders"
    return ", ".join(names[:12]) + (", …" if len(names) > 12 else "")


def listed_name(folder: Path, part: str) -> str | None:
    """`part` as `folder` lists it: that very name, else the one name equal to it in Unicode NFC form."""
    try:
        names = [entry.name for entry in folder.iterdir()]
    except OSError:
        return None
    if part in names:
        return part
    same = [name for name in names if unicodedata.normalize("NFC", name) == unicodedata.normalize("NFC", part)]
    return same[0] if len(same) == 1 else None


def resolve(workspace: Path, folder: str) -> tuple[Path | None, str | None]:
    """The folder's path in the workspace, spelled as the file system lists it, or why it names none."""
    problem = folder_problem(folder)
    if problem:
        return None, problem
    if folder == ".":
        return workspace, None
    root = workspace
    for part in folder.split("/"):
        name = listed_name(root, part)
        kind = "missing" if name is None else kind_of(root / name)
        if kind == "link":
            return None, f"{folder} goes through a symlink; pass a real folder"
        if kind == "locked":
            return None, f"{folder} cannot be read"
        if kind != "folder":
            return None, f"No folder {folder} in your File Organizer agent folder; it holds {top_level(workspace)}. Pass one of these, or ."
        root = root / name
    return root, None


def under_organized(path: str) -> bool:
    key = path_key(path)
    return key == ORGANIZED or key.startswith(ORGANIZED + "/")


def planned_folders(steps: list[Step]) -> set[str]:
    """Every folder this run's moves need."""
    folders = set()
    for step in steps:
        if step.action == MOVE and step.quota:
            folders.update(parents(step.target))
    return folders


def conflicts(steps: list[Step], paths: list[str], files: list[str]) -> list[str]:
    """Folders this run needs that exist as a file, or exist spelled in another letter case or Unicode form."""
    existing = set(paths)
    by_key: dict[str, str] = {}
    for path in paths:
        by_key.setdefault(path_key(path), path)
    as_files = set(files)
    problems = []
    for folder in sorted(planned_folders(steps)):
        if folder in as_files:
            problems.append(f"{folder} is a file, but the rules need a folder there; rename it")
        elif folder not in existing and path_key(folder) in by_key:
            problems.append(f"{by_key[path_key(folder)]} differs from {folder} only in letter case or Unicode form; rename it to {folder}")
    return problems


def entries_after(scanned: Scan, steps: list[Step]) -> int:
    """The files and folders the agent folder holds after this run, as RUSH Lab counts them: every entry
    the run leaves as it was, the folder itself, inside it every file at its end path with its folders
    (and the folders that hold a hidden entry), and the plugin's state folder and file."""
    prefix = scanned.prefix
    alive: set[str] = set()
    for step in steps:
        if step.quota and step.action == DELETE:
            continue
        end = step.target if step.quota else step.path
        alive.add(end)
        alive.update(parents(end))
    for entry in scanned.kept:
        if inside(entry.path, prefix) and not entry.path.startswith(STATE_DIR + "/"):
            alive.update(parents(within(entry.path, prefix)))
    kept_inside = {within(entry.path, prefix) for entry in scanned.kept if inside(entry.path, prefix)}
    return len(scanned.kept) + len(alive - kept_inside) + (1 if prefix else 0) + 2


def refusal(folder: str, prefix: str, why: str) -> Layout:
    return Layout(folder, prefix, [], [], [], [], {}, 0, 12, why)


def look(workspace: Path, folder: str, read_kept: bool = False) -> Layout:
    """The folder under the rules; `refused` says why the rules refuse it (then facts and steps are empty).
    With `read_kept`, it also reads every file the run leaves as it was, for the answer key."""
    root, problem = resolve(workspace, folder)
    if root is None:
        return refusal(folder, "", problem)
    scanned = scan(workspace, root)
    problems = scanned.problems + limit_problems(scanned)
    if not scanned.files and not problems:
        return refusal(folder, scanned.prefix, f"{label(folder)} holds no files to organize (hidden files are left alone)")
    facts = []
    for relative in scanned.files if not problems else ():
        try:
            data = root.joinpath(relative).read_bytes()
        except OSError:
            problems.append(f"{scanned.prefix + '/' if scanned.prefix else ''}{relative} cannot be read")
            continue
        facts.append(describe(relative, data))
    digests: dict[str, str] = {}
    if read_kept and not problems:
        digests, unread = kept_digests(workspace, scanned.kept)
        problems += unread
    if problems:
        return refusal(folder, scanned.prefix, cannot(folder, problems))
    facts = ordered(facts)
    empty = set(scanned.empty)
    existing = sorted(path for path in (*scanned.files, *scanned.folders) if path not in empty)
    taken = [path for path in existing if under_organized(path)]
    steps = plan(facts, taken)
    problems = conflicts(steps, existing, list(scanned.files))
    after = entries_after(scanned, steps)
    if after > MAX_ENTRIES:
        problems.append(
            f"after this run your File Organizer agent folder would hold {after} files and folders; RUSH Lab saves at most"
            f" {SAVED_ENTRIES:,} (the rules allow {MAX_ENTRIES:,}): move some files out first"
        )
    return Layout(
        folder, scanned.prefix, facts, steps, taken, scanned.kept, digests, after, hash_length(facts), cannot(folder, problems) if problems else None
    )


def cannot(folder: str, problems: list[str]) -> str:
    shown = "; ".join(problems[:SHOWN_PROBLEMS])
    more = len(problems) - SHOWN_PROBLEMS
    return f"The rules cannot organize {label(folder)}: {shown}" + (f"; and {more} more" if more > 0 else "")
