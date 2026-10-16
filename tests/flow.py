"""The tools run in-process the way runs follow one another: each run is a fresh plugin process (its
RUN state reset), surveys, and applies the scripted agent's decisions. Tests and build_cases use it."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

from messy import unpack

import verifier
from contract import ApplyInput, Move, OrganizeInput
from plugin import organizer

TASK = "organize-folder"

AGENT_FILE = Path(__file__).resolve().parent / "cases" / "agent.py"


def agent():
    spec = importlib.util.spec_from_file_location("scripted_agent", AGENT_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def plain_rows(survey) -> list[dict]:
    return [{"i": row.i, "path": row.path, "h": row.h, "base": row.base, "drop": row.drop.value if row.drop else None} for row in survey.rows]


def one_run(workspace: Path, folder: str):
    """One run as the instructions say: survey, then apply the decisions in calls of 30."""
    organizer.RUN = None
    survey = organizer.survey(OrganizeInput(folder=folder), workspace)
    outputs = {"survey": {"rows": plain_rows(survey)}}
    agent().decide(outputs, folder)
    last = survey.summary
    errors = []
    for batch in (outputs["batch0"], outputs["batch1"]):
        applied = organizer.apply(ApplyInput(folder=batch["folder"], moves=[Move(**move) for move in batch["moves"]], deletes=batch["deletes"]), workspace)
        errors += applied.errors
        last = applied.summary
    organizer.RUN = None
    return survey, last, errors


def organize_fully(workspace: Path, folder: str, most: int = 40) -> int:
    """Runs until a survey has nothing to do; how many runs that took."""
    for count in range(1, most + 1):
        survey, _last, errors = one_run(workspace, folder)
        assert not errors, errors
        if not survey.rows:
            return count
    raise AssertionError(f"{folder} still had work after {most} runs")


def tree(root: Path) -> dict[str, bytes]:
    """Every file under `root` (hidden ones too), by relative path."""
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def host_run(tmp_path: Path, files: dict[str, bytes], folder: str, mistake: str | None = None):
    """The task as the host runs it: the pin from a scratch copy (symlinks followed, as NanoAgent's
    staging copies), then survey and two applies, every output checked; (workspace, pin, last summary)."""
    workspace, scratch = tmp_path / "workspace", tmp_path / "scratch"
    unpack(files, workspace)
    shutil.copytree(workspace, scratch)
    organizer.RUN = None
    reference = organizer.pin_layout(OrganizeInput(folder=folder), scratch)
    assert verifier.verify_output("pin_layout", OrganizeInput(folder=folder), reference, str(scratch))["valid"]
    survey = organizer.survey(OrganizeInput(folder=folder), workspace)
    assert verifier.verify_output("survey", OrganizeInput(folder=folder), survey, str(workspace))["valid"]
    outputs = {"survey": {"rows": plain_rows(survey)}}
    agent().decide(outputs, folder, mistake)
    last = survey.summary
    for batch in (outputs["batch0"], outputs["batch1"]):
        given = ApplyInput(folder=folder, moves=[Move(**move) for move in batch["moves"]], deletes=batch["deletes"])
        applied = organizer.apply(given, workspace)
        check = verifier.verify_output("apply", given, applied, str(workspace))
        assert check["valid"], check["message"]
        last = applied.summary
    organizer.RUN = None
    return workspace, reference, last


def judge(workspace: Path, reference, output, folder: str) -> dict:
    """verify_task, called twice as NanoAgent does: the two verdicts must agree."""
    first = verifier.verify_task(TASK, OrganizeInput(folder=folder), output, reference, str(workspace))
    assert first == verifier.verify_task(TASK, OrganizeInput(folder=folder), output, reference, str(workspace))
    return first


def failed(verdict: dict) -> list[str]:
    return [entry["id"] for entry in verdict["details"]["constraints"] if entry["ok"] is False]
