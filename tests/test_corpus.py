"""The rules on real files from the web (tests/corpus/sources.json; fetch with tests/corpus/fetch.py):
each file's facts are the recorded ones and the independent oracle's, real-file folders agree with the
oracle, and organizing them converges without losing anything."""

from __future__ import annotations

from pathlib import Path

import pytest
from corpus.real import CACHE, entries, pools
from flow import organize_fully, tree
from messy import messy, unpack
from oracle.oracle import facts as oracle_facts
from test_differential import differences
from test_properties import kept_contents

from plugin import organizer
from plugin.layout import look
from plugin.walk import describe

pytestmark = pytest.mark.corpus


@pytest.mark.parametrize("entry", entries(), ids=lambda entry: entry["name"])
def test_each_real_file_reads_as_recorded(entry: dict) -> None:
    data = (CACHE / entry["name"]).read_bytes()
    found = describe(entry["name"], data)
    assert {"group": found.group, "type": found.type, "ext": found.ext, "date": found.date} == entry["expect"]
    oracle = oracle_facts(entry["name"], data)
    assert {key: oracle[key] for key in ("group", "type", "ext", "date", "slug", "base")} == {
        "group": found.group, "type": found.type, "ext": found.ext, "date": found.date, "slug": found.slug, "base": found.base,
    }  # fmt: skip


@pytest.mark.parametrize("seed", range(20))
def test_real_file_folders_agree_with_the_oracle(tmp_path: Path, seed: int) -> None:
    profile = ["small", "medium", "multirun", "edge"][seed % 4]
    unpack(messy(seed, profile, "Downloads", real=pools()), tmp_path)
    problems = differences(tmp_path, "Downloads")
    assert not problems, "\n".join(problems[:15])


@pytest.mark.parametrize("seed", range(6))
def test_real_file_folders_organize_completely(tmp_path: Path, seed: int) -> None:
    files = messy(seed, "medium", "Downloads", real=pools())
    unpack(files, tmp_path)
    organizer.RUN = None
    organize_fully(tmp_path, "Downloads")
    final = look(tmp_path, "Downloads")
    assert all(step.action == "stay" for step in final.steps)
    assert kept_contents(tree(tmp_path), "Downloads") == kept_contents(files, "Downloads")
