"""R2-02: at the published limits (1,000 files, 200 MiB, a 1 GiB agent folder) every verifier call stays
under 20 s on the development Mac, well inside NanoAgent's 60 s for the two runs of each call.

Each folder of tests/perf/worst.py (dense Office files, an organized folder of them, the review's
perf_dense45/90, the costliest file of every kind, the 1 GiB agent folder) runs organize-folder through
NanoAgent's own task runner and verifier helper (tests/perf/verifier_times.py, NanoAgent's Python,
seatbelt), every verifier call timed. Where NanoAgent is not installed, the same verifier functions are
timed in-process, twice each, as the helper runs them.

Opt-in (a few minutes, up to 1 GiB of temporary files): FILE_ORGANIZER_PERF=1 uv run pytest -m perf
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from flow import plain_rows
from messy import unpack
from perf import worst

import verifier
from contract import ApplyInput, Move, OrganizeInput
from plugin import organizer

pytestmark = pytest.mark.perf
ROOT = Path(__file__).resolve().parents[1]
NANOAGENT_PYTHON = Path.home() / "mochi-dev" / "rushlab" / "nanoagent" / ".venv" / "bin" / "python"
HARNESS = Path.home() / "mochi-dev" / "harness"
LIMIT = 20.0
FOLDERS = sorted(worst.FOLDERS)


@pytest.mark.skipif(not NANOAGENT_PYTHON.is_file() or not HARNESS.is_dir(), reason="needs NanoAgent's Python and the lab harness")
@pytest.mark.parametrize("folder", FOLDERS)
def test_every_verifier_call_through_nanoagent_stays_under_20_s(tmp_path: Path, folder: str) -> None:
    out = tmp_path / "times.json"
    done = subprocess.run(
        [str(NANOAGENT_PYTHON), str(ROOT / "tests" / "perf" / "verifier_times.py"), str(ROOT), folder, "--sandbox", "seatbelt", "--harness", str(HARNESS), "--out", str(out)],
        capture_output=True, text=True, timeout=1800, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr[-3000:]
    report = json.loads(out.read_text())
    assert report["valid"] and report["score"] == 1.0, report["message"]
    assert {call["function"] for call in report["calls"]} >= {"verify_output", "verify_task"}
    slow = [call for call in report["calls"] if call["seconds"] >= LIMIT]
    assert not slow, slow


@pytest.mark.parametrize("folder", FOLDERS)
def test_every_verifier_function_run_twice_in_process_stays_under_20_s(tmp_path: Path, folder: str) -> None:
    workspace, scratch = tmp_path / "workspace", tmp_path / "scratch"
    unpack(worst.FOLDERS[folder](), workspace)
    shutil.copytree(workspace, scratch)
    given = OrganizeInput(folder="Downloads")
    organizer.RUN = None
    pin = organizer.pin_layout(given, scratch)
    times = {"pin_layout": twice(lambda: verifier.verify_output("pin_layout", given, pin, str(scratch)))}
    survey = organizer.survey(given, workspace)
    times["survey"] = twice(lambda: verifier.verify_output("survey", given, survey, str(workspace)))
    rows = plain_rows(survey)
    call = ApplyInput(folder="Downloads", moves=[Move(i=row["i"], n=1) for row in rows if not row["drop"]][:30], deletes=[row["i"] for row in rows if row["drop"]][:30])
    applied = organizer.apply(call, workspace)
    times["apply"] = twice(lambda: verifier.verify_output("apply", call, applied, str(workspace)))
    organizer.RUN = None
    times["task"] = twice(lambda: verifier.verify_task("organize-folder", given, applied.summary, pin, str(workspace)))
    assert all(seconds < LIMIT for seconds in times.values()), times


def twice(check) -> float:
    started = time.perf_counter()
    first, second = check(), check()
    assert first == second
    return time.perf_counter() - started
