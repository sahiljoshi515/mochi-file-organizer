"""Shared helpers: path confinement to a folder, and hashing."""

from __future__ import annotations

import hashlib
from pathlib import Path

# Folders a tool never touches inside the workspace.
PROTECTED = frozenset({".judge"})


def confine(root: Path, relative: str) -> Path:
    """The path `relative` names inside `root`.

    It may not be empty, absolute, hold NUL, climb out with `..`, start in a protected folder, or
    escape through a symlink anywhere along it.
    """
    if not relative or "\x00" in relative:
        raise ValueError("a path must be a non-empty path relative to the folder")
    parts = Path(relative)
    if parts.is_absolute() or ".." in parts.parts or parts.parts[0] in PROTECTED:
        raise ValueError(f"{relative}: paths must stay inside the folder")
    base = root.resolve()
    path = base / parts
    # Resolve through the deepest existing ancestor, so a symlink inside cannot point outside.
    probe = path
    while not probe.exists() and probe != base:
        probe = probe.parent
    if probe.resolve() != base and not probe.resolve().is_relative_to(base):
        raise ValueError(f"{relative}: paths must stay inside the folder")
    return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()
