"""The real-file corpus as pools of bytes by sample kind, for tests/messy.py (`real=`)."""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "corpus-cache"
# the builder kind each real file stands in for
KIND = {"jpg": "jpg", "webp": "webp", "png": "png", "gif": "gif", "tiff": "tiff", "avif": "avif", "heic": "heic", "docx": "docx", "xlsx": "xlsx", "pptx": "pptx", "odt": "odt", "ods": "ods", "odp": "odp", "mp4": "mp4", "webm": "webm", "mp3": "mp3", "ogg": "ogg", "wav": "wav", "svg": "svg", "txt": "txt", "html": "html", "epub": "epub", "pdf": "pdf", "py": "py", "csv": "csv", "json": "json", "md": "md", "gz": "gz", "whl": "zip"}


def entries() -> list[dict]:
    return json.loads((HERE / "sources.json").read_text(encoding="utf-8"))["files"]


def available() -> bool:
    return CACHE.is_dir() and all((CACHE / entry["name"]).is_file() for entry in entries())


def pools() -> dict[str, list[bytes]]:
    found: dict[str, list[bytes]] = {}
    for entry in entries():
        kind = KIND.get(entry["expect"]["type"] if entry["expect"]["type"] != "whl" else "whl")
        if kind:
            found.setdefault(kind, []).append((CACHE / entry["name"]).read_bytes())
    return found
