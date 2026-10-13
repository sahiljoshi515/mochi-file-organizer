"""Checks shared by the tool verifiers. Pure functions of their arguments and the files on disk."""

import json
from pathlib import Path

from .rules import ROOT, root_name

MAX_SEED = 999_999_999
SHA256 = 64
# Where a task root's file numbers are recorded: beside it, as <root>.ids.json.
LEDGER_SUFFIX = ".ids.json"


def result(valid, message, *, score=None, **details):
    return {
        "valid": valid,
        "score": float(valid) if score is None else score,
        "message": message,
        "details": details,
    }


def seed_problem(value):
    """What is wrong with a task input's seed, or None."""
    if not 0 <= value.seed <= MAX_SEED:
        return f"seed must be between 0 and {MAX_SEED}"
    return None


def root_problem(root):
    """What is wrong with a task root, or None: it must be file-organizer/<seed>-<size>."""
    if not ROOT.fullmatch(root):
        return "root must be file-organizer/<seed>-<size>"
    return None


def relative_problem(name, path):
    """What is wrong with a path inside the task root, or None."""
    if not path or path.endswith("/") or "\x00" in path:
        return f"{name} must be a file path relative to root"
    parts = Path(path)
    if parts.is_absolute() or ".." in parts.parts:
        return f"{name} must stay inside root"
    if parts.parts[0] == ".judge":
        return f"{name} may not be under .judge"
    return None


def is_sha256(text):
    return len(text) == SHA256 and all(character in "0123456789abcdef" for character in text)


def task_root(workspace, value):
    """The task's folder in the workspace for a task input (seed and size)."""
    return Path(workspace) / root_name(value.seed, value.size.value)


def read_ledger(workspace, root):
    """The folder's record of file numbers, {"files": {number: path}, "deleted": {number: path}}, or None."""
    path = Path(workspace) / (root + LEDGER_SUFFIX)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict) or not isinstance(data.get("deleted"), dict):
        return None
    return data
