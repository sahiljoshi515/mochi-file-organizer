"""The page: ui/ holds only the renderer and its styles, the renderer reaches for nothing outside its
output, and (when Node and the lab's page check are installed) it draws a result."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGE_CHECK = Path.home() / "mochi-dev" / "harness" / "page_check.sh"
GLOBALS = ("document", "window", "globalThis", "self", "parent", "top", "opener", "frames", "location", "history", "navigator", "postMessage", "eval", "Function", "fetch", "XMLHttpRequest", "WebSocket", "EventSource", "localStorage", "sessionStorage", "indexedDB")


def test_ui_holds_only_the_renderer() -> None:
    assert sorted(path.name for path in (ROOT / "ui").iterdir()) == ["renderers.css", "renderers.js"]
    code = (ROOT / "ui" / "renderers.js").read_text(encoding="utf-8")
    assert "export default {" in code and "OrganizeOutput:" in code
    for name in GLOBALS:
        assert not re.search(rf"(?<![\w$.]){name}(?![\w$])(?!\s*:)", re.sub(r'"[^"]*"|`[^`]*`|//.*', "", code)), name


@pytest.mark.skipif(not PAGE_CHECK.is_file() or shutil.which("node") is None, reason="needs node and the lab's page_check.sh")
def test_the_renderer_draws_a_result(tmp_path: Path) -> None:
    sample = tmp_path / "sample.json"
    sample.write_text(json.dumps({"folder": "Downloads", "files": 45, "moved": 31, "deleted": 14, "stayed": 0, "left": 0, "remaining": 12}))
    done = subprocess.run(["bash", str(PAGE_CHECK), str(ROOT), f"OrganizeOutput={sample}"], capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "31 moved" in done.stdout
