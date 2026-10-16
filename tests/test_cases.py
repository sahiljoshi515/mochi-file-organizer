"""Every scripted case replayed without NanoAgent, the way the host runs it: the reference pinned from a
scratch copy of the agent folder, every tool call checked by verify_input and verify_output, the
python steps run, the submitted summary judged by verify_task, and the verdict as the case expects."""

from __future__ import annotations

import json
import os
import random
import shutil
import tarfile
from pathlib import Path

import pytest
from slimconfig import build_output, plain_output

import verifier
from contract import TASKS, TOOLS, OrganizeInput, Task, Tool
from plugin import organizer

CASES = sorted((Path(__file__).resolve().parent / "cases").glob("*.json"))
IMPLEMENTATIONS = {Tool.PIN_LAYOUT: organizer.pin_layout, Tool.SURVEY: organizer.survey, Tool.APPLY: organizer.apply}


def resolve(value, outputs):
    if isinstance(value, str) and value.startswith("$ref:"):
        node = outputs
        for part in value[5:].split("."):
            node = node[int(part)] if isinstance(node, list) else node[part]
        return node
    if isinstance(value, list):
        return [resolve(item, outputs) for item in value]
    if isinstance(value, dict):
        return {key: resolve(item, outputs) for key, item in value.items()}
    return value


def scramble(folder: Path, seed: str) -> None:
    rng = random.Random(seed)
    for path in sorted(folder.rglob("*"), key=str):
        stamp = rng.randrange(978_307_200, 1_893_456_000)
        os.utime(path, (stamp, stamp))


def call(tool: Tool, arguments: dict, workspace: Path):
    given_class, _made = TOOLS[tool]
    given = build_output(arguments, given_class)
    checked = verifier.verify_input(tool.value, given)
    if not checked["valid"]:
        raise ValueError(checked["message"])
    output = IMPLEMENTATIONS[tool](given, workspace)
    checked = verifier.verify_output(tool.value, given, output, str(workspace))
    assert checked["valid"], f"{tool.value}: {checked['message']}"
    return output


@pytest.mark.parametrize("case_path", CASES, ids=[path.stem for path in CASES])
def test_case(tmp_path: Path, case_path: Path) -> None:
    case = json.loads(case_path.read_text(encoding="utf-8"))
    workspace, scratch = tmp_path / "workspace", tmp_path / "scratch"
    workspace.mkdir()
    with tarfile.open(case_path.parent / case["agent_folder"]) as archive:
        archive.extractall(workspace, filter="data")
    if case.get("mtimes") == "scrambled":
        scramble(workspace, "workspace")
    shutil.copytree(workspace, scratch)
    if case.get("mtimes") == "scrambled":
        scramble(scratch, "scratch")
    arguments = OrganizeInput(**case["arguments"])
    organizer.RUN = None
    reference = call(Tool.PIN_LAYOUT, case["arguments"], scratch)
    organizer.RUN = None  # the agent's own plugin process
    outputs: dict = {}
    submitted = None
    try:
        for step in case["steps"]:
            if "python" in step:
                exec(step["python"], {"workspace": workspace, "outputs": outputs, "json": json, "Path": Path})  # noqa: S102
                continue
            arguments_given = resolve(step.get("arguments", {}), outputs)
            if step["tool"] == "submit":
                submitted = build_output(arguments_given, TASKS[Task.ORGANIZE_FOLDER][1])
                continue
            if step.get("expect_error"):
                with pytest.raises(ValueError):
                    call(Tool(step["tool"]), arguments_given, workspace)
                continue
            output = call(Tool(step["tool"]), arguments_given, workspace)
            if step.get("save_as"):
                outputs[step["save_as"]] = json.loads(json.dumps(plain_output(output)))
    finally:
        organizer.RUN = None
    assert submitted is not None, "the case never submits"
    verdict = verifier.verify_task(Task.ORGANIZE_FOLDER.value, arguments, submitted, reference, str(workspace))
    expect = case["expect"]
    assert verdict["valid"] == expect["valid"], verdict["message"]
    assert verdict["score"] >= expect.get("score_min", 0.0) and verdict["score"] <= expect.get("score_max", 1.0), verdict["message"]
    assert expect.get("message_contains", "") in verdict["message"], verdict["message"]
    assert verdict["valid"] == (verdict["score"] == 1.0)


def test_every_case_fits_the_hosted_steps_and_ends_in_submit() -> None:
    for path in CASES:
        steps = [step for step in json.loads(path.read_text(encoding="utf-8"))["steps"] if "tool" in step]
        assert steps[-1]["tool"] == "submit", path.name
        assert len(steps) <= 5, path.name  # the hosted runner's 6th step may not call tools


def test_the_cases_cover_every_wrong_row() -> None:
    names = {path.stem for path in CASES}
    for row in ("keeper_wrong", "duplicate_kept", "rank_swapped", "skipped_batch", "junk_as_move", "fabricated_summary", "tamper_after_apply", "stray_file", "copied_not_moved", "out_of_quota"):
        assert f"wrong_{row}" in names
    for tamper in (
        "hidden_deleted", "hidden_modified", "hidden_stray_copy", "duplicate_hidden", "duplicate_into_hidden_folder", "junk_hidden",
        "outside_deleted", "outside_modified", "duplicate_moved_outside", "empty_folder_left", "junk_replaced_by_folder",
        "fifo_added", "unreadable_target", "unreadable_input", "symlink_file", "symlink_folder", "state_stash_file", "state_stash_folder",
    ):  # fmt: skip
        assert f"wrong_{tamper}" in names  # the review's red team (FO-01 to FO-05)
    assert sum(name.startswith("gold_") for name in names) >= 7
