"""Properties the rules promise, over many generated folders: organizing converges and is a fixed
point, modification times never matter, and no run ever loses a content it should keep."""

from __future__ import annotations

import hashlib
import os
import random
from pathlib import Path

import pytest
from flow import one_run, organize_fully, tree
from messy import messy, organized_folder, unpack

from contract import ApplyInput, OrganizeInput
from plugin import organizer
from plugin.layout import look
from plugin.naming import is_hidden, is_junk


@pytest.fixture(autouse=True)
def fresh_run():
    organizer.RUN = None
    yield
    organizer.RUN = None


def kept_contents(files: dict[str, bytes], folder: str) -> set[str]:
    """The contents the rules keep: every non-junk, non-empty file inside the folder, outside hidden ones."""
    prefix = "" if folder == "." else folder + "/"
    out = set()
    for path, data in files.items():
        if not path.startswith(prefix):
            continue
        parts = path[len(prefix) :].split("/")
        if any(is_hidden(part) for part in parts) or is_junk(parts[-1]) or not data:
            continue
        out.add(hashlib.sha256(data).hexdigest())
    return out


@pytest.mark.parametrize("seed", range(24))
def test_organizing_converges_to_a_fixed_point_that_keeps_every_content(tmp_path: Path, seed: int) -> None:
    profile = ["small", "medium", "multirun", "edge"][seed % 4]
    folder = "." if seed % 5 == 0 else "Downloads"
    files = organized_folder(seed, "Photos") if seed % 6 == 1 else messy(seed, profile, folder)
    folder = "Photos" if seed % 6 == 1 else folder
    unpack(files, tmp_path)
    runs = organize_fully(tmp_path, folder)
    assert runs >= 1
    final = look(tmp_path, folder)
    assert final.refused is None and all(step.action == "stay" for step in final.steps)
    assert all(fact.conforming for fact in final.facts)
    after = {path: data for path, data in tree(tmp_path).items() if not path.startswith(".file-organizer/")}
    assert kept_contents(after, folder) == kept_contents(files, folder)
    for path, data in files.items():  # hidden files, and everything outside the folder, are untouched
        inside = folder == "." or path.startswith(folder + "/")
        relative = path[len(folder) + 1 :] if inside and folder != "." else path
        if not inside or any(is_hidden(part) for part in relative.split("/")):
            assert after.get(path) == data, path


@pytest.mark.parametrize("seed", range(12))
def test_modification_times_never_change_the_plan(tmp_path: Path, seed: int) -> None:
    files = messy(seed, "medium", "Downloads")
    first, second = tmp_path / "a", tmp_path / "b"
    unpack(files, first)
    unpack(files, second)
    rng = random.Random(seed)
    for path in second.rglob("*"):
        stamp = rng.randrange(0, 2_000_000_000)
        os.utime(path, (stamp, stamp))
    one, two = look(first, "Downloads"), look(second, "Downloads")
    assert one.facts == two.facts and one.steps == two.steps


@pytest.mark.parametrize("seed", range(10))
def test_no_apply_ever_loses_a_content(tmp_path: Path, seed: int) -> None:
    """An agent that deletes every row it can: copies and junk go, but every content stays somewhere."""
    files = messy(seed, "small", "Downloads")
    unpack(files, tmp_path)
    survey = organizer.survey(OrganizeInput(folder="Downloads"), tmp_path)
    for start in range(0, len(survey.rows), 30):
        organizer.apply(ApplyInput(folder="Downloads", moves=[], deletes=[row.i for row in survey.rows[start : start + 30]]), tmp_path)
    after = tree(tmp_path)
    assert kept_contents(after, "Downloads") == kept_contents(files, "Downloads")


def test_a_big_folder_takes_several_runs_of_at_most_60_actions(tmp_path: Path) -> None:
    unpack(messy(4, "multirun", "Downloads"), tmp_path)
    counts = []
    while True:
        organizer.RUN = None
        survey = organizer.survey(OrganizeInput(folder="Downloads"), tmp_path)
        counts.append(len(survey.rows))
        if not survey.rows:
            break
        one_run(tmp_path, "Downloads")
    assert len(counts) >= 3 and max(counts) == 60 and counts[-1] == 0
