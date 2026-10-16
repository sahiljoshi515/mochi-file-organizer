"""The plugin's rules against the independent oracle (tests/oracle/oracle.py, written from RULES.md with
other tools), over 200 seeded messy folders: every file's facts and every step must agree exactly."""

from __future__ import annotations

from pathlib import Path

import pytest
from builders import edge_files
from messy import messy, organized_folder, unpack
from oracle.oracle import facts as oracle_facts
from oracle.oracle import organize

from plugin.layout import look
from plugin.walk import describe

FACT_FIELDS = ("path", "size", "sha256", "junk", "group", "type", "ext", "date", "slug", "base", "conforming")
STEP_FIELDS = ("i", "path", "action", "reason", "copy_of", "target", "quota")
PROFILES = ["small", "medium", "multirun", "edge", "organized"]


def differences(root: Path, folder: str) -> list[str]:
    found = look(root, folder)
    assert found.refused is None, found.refused
    want = organize(str(root if folder == "." else root / folder))
    problems = []
    if [fact.path for fact in found.facts] != [item["path"] for item in want["files"]]:
        problems.append(f"order: {[fact.path for fact in found.facts][:5]} vs {[item['path'] for item in want['files']][:5]}")
    for fact, item in zip(found.facts, want["files"], strict=False):
        for field in FACT_FIELDS:
            if getattr(fact, field) != item[field]:
                problems.append(f"{fact.path}: {field} plugin {getattr(fact, field)!r}, oracle {item[field]!r}")
    for step, item in zip(found.steps, want["steps"], strict=False):
        for field in STEP_FIELDS:
            if getattr(step, field) != item[field]:
                problems.append(f"step {step.i} {step.path}: {field} plugin {getattr(step, field)!r}, oracle {item[field]!r}")
    return problems


@pytest.mark.parametrize("seed", range(200))
def test_the_plugin_and_the_oracle_agree(tmp_path: Path, seed: int) -> None:
    profile = PROFILES[seed % len(PROFILES)]
    folder = "." if seed % 17 == 0 else ("Photos" if profile == "organized" else "Downloads")
    files = organized_folder(seed, folder) if profile == "organized" else messy(seed, profile, folder)
    unpack(files, tmp_path)
    problems = differences(tmp_path, folder)
    assert not problems, "\n".join(problems[:15])


@pytest.mark.parametrize("name", sorted(edge_files()))
def test_edge_files_agree_with_the_oracle(name: str) -> None:
    """The review's edge files (wide and legacy text, the Office family, QuickTime, MPEG-TS, CR3, PDF
    information, JSON depth, zip end records, …): the plugin and the oracle read each one alike."""
    data = edge_files()[name]
    fact = describe(name, data)
    want = oracle_facts(name, data)
    assert {field: getattr(fact, field) for field in FACT_FIELDS} == {field: want[field] for field in FACT_FIELDS}
