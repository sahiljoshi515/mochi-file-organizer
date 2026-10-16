"""A whole folder under the rules: which folder the task names, what the rules plan for it, and every
reason RULES.md §1 refuses it (limits, case conflicts, the 5,000 entries RUSH Lab saves).

Shared, byte for byte, by src/plugin/ and verifier/: the tools refuse a folder whose layout is `refused`,
and the verifier re-derives the same plan with `look` to check the answer key and the survey.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .naming import ORGANIZED, path_key
from .plan import DELETE, MOVE, Step, hash_length, ordered, plan
from .walk import MAX_ENTRIES, Facts, Scan, count_below, describe, limit_problems, scan

STATE_DIR = ".file-organizer"
FOLDER_LIMIT = 100
FOLDER_PART = re.compile(r"[^/\\\x00]+")
SHOWN_PROBLEMS = 6
SAVED_ENTRIES = 5000


@dataclass(frozen=True)
class Layout:
    folder: str
    facts: list[Facts]  # in the rules' order: facts[i] is file i
    steps: list[Step]
    taken: list[str]
    hidden: int
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


def top_level(workspace: Path) -> str:
    names = sorted(entry.name + "/" for entry in workspace.iterdir() if entry.is_dir() and not entry.is_symlink() and not entry.name.startswith("."))
    if not names:
        return "no folders"
    return ", ".join(names[:12]) + (", …" if len(names) > 12 else "")


def resolve(workspace: Path, folder: str) -> tuple[Path | None, str | None]:
    """The folder's path in the workspace, or why it names none."""
    problem = folder_problem(folder)
    if problem:
        return None, problem
    if folder == ".":
        return workspace, None
    root = workspace
    for part in folder.split("/"):
        root = root / part
        if root.is_symlink():
            return None, f"{folder} goes through a symlink; pass a real folder"
    if not root.is_dir():
        return None, f"No folder {folder} in your File Organizer agent folder; it holds {top_level(workspace)}. Pass one of these, or ."
    return root, None


def under_organized(path: str) -> bool:
    key = path_key(path)
    return key == ORGANIZED or key.startswith(ORGANIZED + "/")


def planned_folders(steps: list[Step]) -> set[str]:
    """Every folder this run's moves need."""
    folders = set()
    for step in steps:
        if step.action == MOVE and step.quota:
            parts = step.target.split("/")
            folders.update("/".join(parts[:end]) for end in range(1, len(parts)))
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


def entries_after(workspace: Path, root: Path, scanned: Scan, steps: list[Step]) -> int:
    """The files and folders the agent folder holds after this run, as RUSH Lab counts them: what lies
    outside the folder as it is, inside it every file at its end path with its folders, the hidden
    entries, and the plugin's own state folder and file."""
    outside = 0
    if root != workspace:
        stack = [workspace]
        while stack:
            for entry in stack.pop().iterdir():
                if entry == workspace / STATE_DIR:
                    continue
                outside += 1
                if entry != root and entry.is_dir() and not entry.is_symlink():
                    stack.append(entry)
    inside: set[str] = set()
    for step in steps:
        if step.quota and step.action == DELETE:
            continue
        parts = (step.target if step.quota else step.path).split("/")
        inside.update("/".join(parts[:end]) for end in range(1, len(parts) + 1))
    hidden = scanned.hidden
    if root == workspace and (workspace / STATE_DIR).is_dir():
        hidden -= 1 + count_below(workspace / STATE_DIR)
    return outside + len(inside) + hidden + 2


def look(workspace: Path, folder: str) -> Layout:
    """The folder under the rules; `refused` says why the rules refuse it (then facts and steps may be empty)."""
    root, problem = resolve(workspace, folder)
    if root is None:
        return Layout(folder, [], [], [], 0, 0, 12, problem)
    scanned = scan(root)
    prefix = "" if folder == "." else folder + "/"
    problems = scanned.problems + limit_problems(scanned, root, prefix)
    if not scanned.files and not problems:
        return Layout(folder, [], [], [], scanned.hidden, 0, 12, f"{label(folder)} holds no files to organize (hidden files are left alone)")
    if problems:
        return Layout(folder, [], [], [], scanned.hidden, 0, 12, cannot(folder, problems))
    facts = ordered([describe(relative, root.joinpath(relative).read_bytes()) for relative in scanned.files])
    taken = [path for path in scanned.paths if under_organized(path)]
    steps = plan(facts, taken)
    problems = conflicts(steps, scanned.paths, scanned.files)
    after = entries_after(workspace, root, scanned, steps)
    if after > MAX_ENTRIES:
        problems.append(
            f"after this run your File Organizer agent folder would hold {after} files and folders; RUSH Lab saves at most"
            f" {SAVED_ENTRIES:,} (the rules allow {MAX_ENTRIES:,}): move some files out first"
        )
    return Layout(folder, facts, steps, taken, scanned.hidden, after, hash_length(facts), cannot(folder, problems) if problems else None)


def cannot(folder: str, problems: list[str]) -> str:
    shown = "; ".join(problems[:SHOWN_PROBLEMS])
    more = len(problems) - SHOWN_PROBLEMS
    return f"The rules cannot organize {label(folder)}: {shown}" + (f"; and {more} more" if more > 0 else "")
