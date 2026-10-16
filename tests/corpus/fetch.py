"""Downloads the real-file corpus listed in tests/corpus/sources.json into tests/corpus/corpus-cache/
(git-ignored: the files are never committed and keep their own licences), checking every sha256.

    uv run python tests/corpus/fetch.py
"""

from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "corpus-cache"


def load() -> list[dict]:
    return json.loads((HERE / "sources.json").read_text(encoding="utf-8"))["files"]


def fetch(entry: dict) -> Path:
    target = CACHE / entry["name"]
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == entry["sha256"]:
        return target
    request = urllib.request.Request(entry["url"], headers={"User-Agent": "file-organizer-tests/0.2"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != entry["sha256"]:
        raise SystemExit(f"{entry['name']}: sha256 {digest} is not the recorded {entry['sha256']} ({entry['url']} changed)")
    CACHE.mkdir(exist_ok=True)
    target.write_bytes(data)
    return target


def main() -> int:
    entries = load()
    for entry in entries:
        fetch(entry)
    print(f"{len(entries)} files in {CACHE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
