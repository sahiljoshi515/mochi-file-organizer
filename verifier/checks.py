"""Verdict shapes shared by the tool checks and the task check, and reading the plugin's run state."""

import re
from pathlib import Path

from .walk import STATE_DIR, STATE_FILE, run_state

SHOWN = 10
PLAIN_WORD = re.compile(r"[a-z]+ ")  # a first word that is a plain word: no path, snake_case name, number or quote


def result(valid, message, *, score=None, **details):
    return {
        "valid": valid,
        "score": float(valid) if score is None else score,
        "message": message,
        "details": details,
    }


def compact(value):
    """A value small enough for a verdict: lists cut to SHOWN entries, mappings to SHOWN keys."""
    if isinstance(value, list) and len(value) > SHOWN:
        return value[:SHOWN] + [f"… and {len(value) - SHOWN} more"]
    if isinstance(value, dict) and len(value) > SHOWN:
        return {**dict(list(value.items())[:SHOWN]), "…": f"{len(value) - SHOWN} more"}
    return value


def sentence(text):
    """``text`` with a capital first letter when it starts with a plain word ("the folder ..."); a path, a
    snake_case name, a number or a quote at its start stays as it is."""
    return text[0].upper() + text[1:] if PLAIN_WORD.match(text) else text


def constraint(key, text, ok, expected=None, actual=None, message=""):
    """One entry of details.constraints, always with the same keys: ok is True (holds), False (fails) or
    None (not checked: a check it needs did not hold); expected and actual where they say something, else
    None; and message, why it fails or why it was not checked ("" when it holds)."""
    return {
        "id": key,
        "constraint": text,
        "ok": ok,
        "expected": compact(expected),
        "actual": compact(actual),
        "message": "" if ok is True else sentence(message or text),
    }


def summary(constraints):
    """A failed verdict's message: the first failing constraint (or, when none fails, the first not
    checked), its id and why, then how many more fail: "nothing-extra: ... (+1 more)"."""
    failed = [entry for entry in constraints if entry["ok"] is False]
    first = failed[0] if failed else next(entry for entry in constraints if entry["ok"] is not True)
    reason = first["message"].removesuffix(".")
    return f"{first['id']}: {reason}" + (f" (+{len(failed) - 1} more)" if len(failed) > 1 else "")


def printable(text):
    """``text`` with each character that does not print written as its escape: the junk name Icon\\r."""
    return "".join(char if char.isprintable() else repr(char)[1:-1] for char in text)


def shown(items):
    """At most SHOWN items of a list, each printable, for a verdict's message."""
    items = [printable(item) for item in items]
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
