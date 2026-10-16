"""Verdict shapes shared by the tool checks and the task check, and reading the plugin's run state."""

import json
from pathlib import Path

from .layout import STATE_DIR

STATE_FILE = "state.json"
SHOWN = 10


def result(valid, message, *, score=None, **details):
    return {
        "valid": valid,
        "score": float(valid) if score is None else score,
        "message": message,
        "details": details,
    }


def constraint(key, text, ok, expected=None, actual=None, message=""):
    """One entry of details.constraints: ok is True, False, or None when it was not checked."""
    return {"id": key, "constraint": text, "ok": ok, "expected": expected, "actual": actual, "message": message}


def shown(items):
    """At most SHOWN items of a list, for a verdict's details."""
    items = list(items)
    return items[:SHOWN] + ([f"… and {len(items) - SHOWN} more"] if len(items) > SHOWN else [])


def plural(count, one, many=None):
    return f"{count} {one if count == 1 else (many or one + 's')}"


def read_state(workspace):
    """The plugin's run state (.file-organizer/state.json), or None when it is missing or not readable."""
    path = Path(workspace) / STATE_DIR / STATE_FILE
    if not path.is_file():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    keys = {"version", "token", "folder", "hash_length", "taken", "rows", "applied", "calls", "summary"}
    return state if isinstance(state, dict) and keys <= set(state) else None


def summary_dict(value):
    return {
        "folder": value.folder,
        "files": value.files,
        "moved": value.moved,
        "deleted": value.deleted,
        "stayed": value.stayed,
        "left": value.left,
        "remaining": value.remaining,
    }
