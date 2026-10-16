"""The verifier: tool checks, and the task check's 11 constraints, each broken on its own."""

from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path

import builders
import pytest
from flow import agent, plain_rows
from messy import messy, unpack

import verifier
from contract import ApplyInput, Move, OrganizeInput, OrganizeOutput
from plugin import organizer

TASK = "organize-folder"
FOLDER = "Downloads"


@pytest.fixture(autouse=True)
def fresh_run():
    organizer.RUN = None
    yield
    organizer.RUN = None


def run(tmp_path: Path, files: dict[str, bytes], folder: str = FOLDER, mistake: str | None = None):
    """The task as the host runs it: the pin from a scratch copy, then survey and two applies."""
    workspace, scratch = tmp_path / "workspace", tmp_path / "scratch"
    unpack(files, workspace)
    shutil.copytree(workspace, scratch)
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
    return workspace, reference, last


def judge(workspace: Path, reference, output, folder: str = FOLDER) -> dict:
    first = verifier.verify_task(TASK, OrganizeInput(folder=folder), output, reference, str(workspace))
    assert first == verifier.verify_task(TASK, OrganizeInput(folder=folder), output, reference, str(workspace))  # deterministic
    return first


def failed(verdict: dict) -> list[str]:
    return [entry["id"] for entry in verdict["details"]["constraints"] if entry["ok"] is False]


@pytest.fixture
def gold(tmp_path: Path):
    return run(tmp_path, messy(1, "small", FOLDER))


def test_a_gold_run_holds_every_constraint(gold) -> None:
    workspace, reference, output = gold
    verdict = judge(workspace, reference, output)
    assert verdict["valid"] and verdict["score"] == 1.0, verdict["message"]
    assert [entry["id"] for entry in verdict["details"]["constraints"]] == [
        "answer-key", "submitted-folder", "folder-present", "every-file-kept", "moved-to-rules-path", "duplicates-and-junk-removed",
        "others-untouched", "nothing-extra", "organized-by-rules", "summary-matches", "saved-back",
    ]  # fmt: skip
    assert all(entry["ok"] is True for entry in verdict["details"]["constraints"])
    assert verdict["message"].startswith("Organized Downloads: moved ")
    assert len(verdict["details"]["rows"]) == reference.quota and all(row["ok"] for row in verdict["details"]["rows"])


def first_move(workspace: Path, reference):
    return next(file for file in reference.files if file.quota and file.action.value == "move")


def first_delete(reference):
    return next(file for file in reference.files if file.quota and file.action.value == "delete")


def break_answer_key(workspace, reference, output):
    files = list(reference.files)
    index = files.index(first_move(workspace, reference))
    files[index] = dataclasses.replace(files[index], target=files[index].target.replace(".", "_9.", 1) if "." in files[index].target else files[index].target + "_9")
    return workspace, dataclasses.replace(reference, files=files), output


def break_folder(workspace, reference, output):
    return workspace, reference, dataclasses.replace(output, folder="Elsewhere")


def break_presence(workspace, reference, output):
    shutil.rmtree(workspace / FOLDER)
    return workspace, reference, output


def break_contents(workspace, reference, output):
    (workspace / FOLDER / first_move(workspace, reference).target).write_bytes(b"lost")
    return workspace, reference, output


def break_placement(workspace, reference, output):
    target = workspace / FOLDER / first_move(workspace, reference).target
    target.rename(target.with_name("elsewhere-" + target.name))
    return workspace, reference, output


def break_deletes(workspace, reference, output):
    deleted = first_delete(reference)
    path = workspace / FOLDER / deleted.path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00\x00\x00\x01Bud1" if deleted.junk else b"back")
    return workspace, reference, output


def break_extra(workspace, reference, output):
    (workspace / FOLDER / "stray.txt").write_text("stray")
    return workspace, reference, output


def break_summary(workspace, reference, output):
    return workspace, reference, dataclasses.replace(output, deleted=output.deleted + 1)


def break_saved_back(workspace, reference, output):
    crowd = workspace / "Crowd"
    crowd.mkdir()
    for index in range(5000):
        (crowd / f"{index}.txt").write_bytes(b"x")
    return workspace, reference, output


BREAKS = {
    "answer-key": break_answer_key,
    "submitted-folder": break_folder,
    "folder-present": break_presence,
    "every-file-kept": break_contents,
    "moved-to-rules-path": break_placement,
    "duplicates-and-junk-removed": break_deletes,
    "nothing-extra": break_extra,
    "summary-matches": break_summary,
    "saved-back": break_saved_back,
}


@pytest.mark.parametrize("constraint", sorted(BREAKS))
def test_each_constraint_fails_when_broken_and_the_score_drops(gold, constraint: str) -> None:
    verdict = judge(*BREAKS[constraint](*gold))
    assert not verdict["valid"] and verdict["score"] < 1.0, verdict["message"]
    assert constraint in failed(verdict), (failed(verdict), verdict["message"])
    assert verdict["message"].split(".")[0].endswith("checks failed") or "checks failed" in verdict["message"]
    if constraint in ("answer-key", "folder-present"):
        assert verdict["score"] == 0.0
        later = [entry for entry in verdict["details"]["constraints"][3:]]
        assert all(entry["ok"] is None for entry in later)


def test_others_untouched_fails_when_a_file_beyond_the_quota_changes(tmp_path: Path) -> None:
    workspace, reference, output = run(tmp_path, messy(4, "multirun", FOLDER))
    waiting = next(file for file in reference.files if not file.quota)
    (workspace / FOLDER / waiting.path).write_bytes(b"changed")
    verdict = judge(workspace, reference, output)
    assert "others-untouched" in failed(verdict) and verdict["score"] < 1.0
    assert verdict["details"]["remaining"] == reference.pending - reference.quota > 0


def test_organized_by_rules_rereads_the_bytes(tmp_path: Path) -> None:
    jpeg = builders.jpeg(3, "2019-07-14")
    workspace, reference, output = run(tmp_path, {"Downloads/photo.jpg": jpeg, "Downloads/x.txt": b"x\n"})
    files = list(reference.files)
    photo = next(index for index, file in enumerate(files) if file.path == "photo.jpg")
    wrong_base = "organized/images/png/2019/2019-07-14_photo.png"  # a forged answer key that calls the JPEG a PNG
    files[photo] = dataclasses.replace(files[photo], group="images", type="png", ext="png", base=wrong_base, target=wrong_base)
    forged = dataclasses.replace(reference, files=files)
    real = workspace / FOLDER / reference.files[photo].target
    moved = workspace / FOLDER / wrong_base
    moved.parent.mkdir(parents=True, exist_ok=True)
    real.rename(moved)
    verdict = judge(workspace, forged, output)
    assert "organized-by-rules" in failed(verdict) and verdict["details"]["constraints"][0]["ok"] is True


def test_verdicts_are_valid_exactly_when_the_score_is_one(tmp_path: Path) -> None:
    for number, mistake in enumerate((None, "keeper_wrong", "duplicate_kept", "rank_swapped", "skipped_batch", "junk_as_move")):
        organizer.RUN = None
        seed = next(seed for seed in range(1, 60) if suits(seed))
        verdict = judge(*run(tmp_path / str(number), messy(seed, "small", FOLDER), mistake=mistake))
        assert verdict["valid"] == (verdict["score"] == 1.0) == (mistake is None), (mistake, verdict["message"])


def suits(seed: int) -> bool:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        unpack(messy(seed, "small", FOLDER), Path(tmp))
        organizer.RUN = None
        rows = plain_rows(organizer.survey(OrganizeInput(folder=FOLDER), Path(tmp)))
        organizer.RUN = None
    helper = agent()
    decided = helper.plan_rows(rows)
    try:
        for mistake in (helper.keeper_wrong, helper.duplicate_kept, helper.rank_swapped, helper.junk_as_move):
            mistake(decided)
    except RuntimeError:
        return False
    return len(rows) <= 60 and len(rows) > 30


def test_tool_inputs_are_checked() -> None:
    assert verifier.verify_input("survey", OrganizeInput(folder="Downloads"))["valid"]
    for folder in (".git", "a/organized", "", "x" * 101, "a/../b"):
        assert not verifier.verify_input("pin_layout", OrganizeInput(folder=folder))["valid"], folder
    ok = ApplyInput(folder="D", moves=[Move(i=1, n=1)], deletes=[2])
    assert verifier.verify_input("apply", ok)["valid"]
    for bad in (
        ApplyInput(folder="D", moves=[Move(i=1, n=1)], deletes=[1]),
        ApplyInput(folder="D", moves=[Move(i=1, n=0)], deletes=[]),
        ApplyInput(folder="D", moves=[Move(i=-1, n=1)], deletes=[]),
        ApplyInput(folder="D", moves=[Move(i=index, n=1) for index in range(61)], deletes=[]),
    ):
        assert not verifier.verify_input("apply", bad)["valid"]


def test_a_tampered_answer_key_fails_its_output_check(tmp_path: Path) -> None:
    unpack(messy(2, "small", FOLDER), tmp_path)
    pin = organizer.pin_layout(OrganizeInput(folder=FOLDER), tmp_path)
    given = OrganizeInput(folder=FOLDER)
    assert verifier.verify_output("pin_layout", given, pin, str(tmp_path))["valid"]
    files = list(pin.files)
    files[0] = dataclasses.replace(files[0], sha256="0" * 64)
    assert not verifier.verify_output("pin_layout", given, dataclasses.replace(pin, files=files), str(tmp_path))["valid"]
    assert not verifier.verify_output("pin_layout", given, dataclasses.replace(pin, quota=pin.quota - 1), str(tmp_path))["valid"]
    assert not verifier.verify_output("pin_layout", given, dataclasses.replace(pin, taken=["organized/x"]), str(tmp_path))["valid"]


def test_survey_and_apply_outputs_must_match_the_disk(tmp_path: Path) -> None:
    unpack(messy(2, "small", FOLDER), tmp_path)
    given = OrganizeInput(folder=FOLDER)
    survey = organizer.survey(given, tmp_path)
    rows = list(survey.rows)
    rows[0] = dataclasses.replace(rows[0], h="f" * 12)
    assert not verifier.verify_output("survey", given, dataclasses.replace(survey, rows=rows), str(tmp_path))["valid"]
    bad_summary = dataclasses.replace(survey.summary, stayed=survey.summary.stayed + 1)
    assert not verifier.verify_output("survey", given, dataclasses.replace(survey, summary=bad_summary), str(tmp_path))["valid"]
    move = next(row for row in survey.rows if row.drop is None)
    call = ApplyInput(folder=FOLDER, moves=[Move(i=move.i, n=1)], deletes=[])
    applied = organizer.apply(call, tmp_path)
    assert verifier.verify_output("apply", call, applied, str(tmp_path))["valid"]
    lied = dataclasses.replace(applied, applied=0, errors=[f"move {move.i}: made up"])
    assert not verifier.verify_output("apply", call, lied, str(tmp_path))["valid"]  # refused, yet the log says this call did it
    stranger = dataclasses.replace(applied, errors=["move 9999: not one of this call's items"])
    assert not verifier.verify_output("apply", call, stranger, str(tmp_path))["valid"]
    hidden_move = ApplyInput(folder=FOLDER, moves=[Move(i=move.i, n=1)], deletes=[])
    destination = tmp_path / FOLDER / next(entry["to"] for entry in organizer.RUN.applied if entry["i"] == move.i)
    destination.unlink()
    assert not verifier.verify_output("apply", hidden_move, applied, str(tmp_path))["valid"]


def test_an_empty_quota_is_valid_only_with_a_true_summary(tmp_path: Path) -> None:
    files = {"Done/organized/documents/txt/undated/undated_a.txt": b"a\n"}
    workspace, reference, output = run(tmp_path, files, folder="Done")
    verdict = judge(workspace, reference, output, folder="Done")
    assert verdict["valid"] and verdict["message"] == "Done is already organized: its one file is in place."
    fake = OrganizeOutput(folder="Done", files=1, moved=1, deleted=0, stayed=1, left=0, remaining=0)
    assert not judge(workspace, reference, fake, folder="Done")["valid"]
