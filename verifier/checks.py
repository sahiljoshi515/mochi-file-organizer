"""Verdict shapes shared by the tool checks and the task check, and reading the plugin's run state."""

from pathlib import Path

from .walk import STATE_DIR, STATE_FILE, run_state

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
    """The plugin's run state (.file-organizer/state.json), or None when it is missing or not the run state."""
    path = Path(workspace) / STATE_DIR / STATE_FILE
    return run_state(path) if path.is_file() else None


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
