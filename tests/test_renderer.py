"""The page: ui/ holds only the renderer and its styles, the renderer reaches for nothing outside its
output, and (when Node and the lab's page check are installed) it draws a result, and the checks list
of the real verdicts of committed cases."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from test_cases import CASES_DIR, played

ROOT = Path(__file__).resolve().parents[1]
PAGE_CHECK = Path.home() / "mochi-dev" / "harness" / "page_check.sh"
KIT = Path.home() / "mochi-dev" / "rushlab" / "nanoagent" / "src" / "nanoagent" / "plugin" / "page" / "kit"
SHIM = Path.home() / "mochi-dev" / "harness" / "page" / "shim.mjs"
DRAW = """
import "./shim.mjs";
import { readFileSync } from "node:fs";
const renderers = (await import("./renderers.js")).default;
const value = JSON.parse(readFileSync("./sample.json", "utf8"));
const verdict = JSON.parse(readFileSync("./verdict.json", "utf8"));
console.log(renderers.OrganizeOutput(value, { task: {}, verdict, send: () => {} }).textContent);
"""
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


@pytest.mark.skipif(not SHIM.is_file() or not KIT.is_dir() or shutil.which("node") is None, reason="needs node and the lab's page kit")
@pytest.mark.parametrize("name", ["gold_small", "wrong_copied_not_moved", "wrong_skipped_batch", "wrong_fifo_added"])
def test_the_checks_list_draws_each_real_verdict(tmp_path: Path, name: str) -> None:
    """A committed case's own summary and verdict: every check with its id; each failure with why and, where
    the verdict has both, what was expected against what was found; each skipped check with what it needed."""
    verdict, output = played(json.loads((CASES_DIR / f"{name}.json").read_text(encoding="utf-8")), tmp_path / "run")
    page = tmp_path / "page"
    shutil.copytree(KIT, page / "kit")
    for file in ("renderers.js", "renderers.css"):
        shutil.copy(ROOT / "ui" / file, page / file)
    shutil.copy(SHIM, page / "shim.mjs")
    (page / "sample.json").write_text(json.dumps(output), encoding="utf-8")
    (page / "verdict.json").write_text(json.dumps(verdict), encoding="utf-8")
    (page / "check.mjs").write_text(DRAW, encoding="utf-8")
    done = subprocess.run(["node", "check.mjs"], cwd=page, capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    entries = verdict["details"]["constraints"]
    held = sum(entry["ok"] is True for entry in entries)
    words = [f"Checks: {held} of {len(entries)} hold", *(entry["constraint"] for entry in entries), *(entry["id"] for entry in entries)]
    words += [entry["message"] for entry in entries if entry["ok"] is not True]
    shows_values = any(entry["ok"] is False and None not in (entry["expected"], entry["actual"]) for entry in entries)
    for word in words:
        assert word in done.stdout, (word, done.stdout)
    assert ("Expected: " in done.stdout) == shows_values
