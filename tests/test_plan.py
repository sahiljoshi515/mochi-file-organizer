"""RULES.md §5: the order, the plan, taken paths, the quota and the hash prefix."""

from __future__ import annotations

from plugin import plan
from plugin.walk import Facts


def fact(path: str, sha: str, *, size: int = 10, junk: bool = False, conforming: bool = False, base: str | None = "organized/data/json/undated/undated_x.json") -> Facts:
    return Facts(path, size, sha, junk, "data", "json", "json", "none", None, None, "x", None if junk or not size else base, conforming)


def test_conforming_files_come_first_then_code_point_order() -> None:
    facts = [fact("b", "1"), fact("B", "2"), fact("organized/x", "3", conforming=True), fact("a", "4")]
    assert [item.path for item in plan.ordered(facts)] == ["organized/x", "B", "a", "b"]


def test_steps_junk_empty_copy_stay_move() -> None:
    facts = plan.ordered(
        [
            fact("a.json", "s1"),
            fact("b.json", "s1"),  # a copy of a.json
            fact(".DS_Store", "s9", junk=True),
            fact("empty.json", "e", size=0),
            fact("organized/data/json/undated/undated_x.json", "s2", conforming=True),
            fact("c.json", "s2"),  # a copy of the file in place
        ]
    )
    steps = plan.plan(facts, ["organized/data/json/undated/undated_x.json"])
    by_path = {step.path: step for step in steps}
    assert by_path["organized/data/json/undated/undated_x.json"].action == "stay"
    assert (by_path[".DS_Store"].action, by_path[".DS_Store"].reason) == ("delete", "junk")
    assert by_path["empty.json"].reason == "empty"
    assert by_path["b.json"].reason == "copy" and by_path["b.json"].copy_of == by_path["a.json"].i
    assert by_path["c.json"].reason == "copy" and by_path["c.json"].copy_of == 0
    # the stay takes its own name, so the first mover gets _2
    assert by_path["a.json"].target == "organized/data/json/undated/undated_x_2.json"


def test_every_existing_path_is_taken_ignoring_case() -> None:
    steps = plan.plan([fact("a.json", "s1")], ["organized/DATA/json/undated/undated_X.json"])
    assert steps[0].target == "organized/data/json/undated/undated_x_2.json"


def test_the_quota_is_the_first_60_actions() -> None:
    facts = plan.ordered([fact(f"f{index:03d}.json", f"s{index}", base=f"organized/data/json/undated/undated_f{index:03d}.json") for index in range(75)])
    steps = plan.plan(facts, [])
    assert [step.quota for step in steps] == [True] * 60 + [False] * 15
    assert plan.counts(steps) == {"files": 75, "stayed": 0, "pending": 75, "quota": 60, "remaining": 15}


def test_nth_free_skips_taken_names() -> None:
    base = "organized/data/json/undated/undated_x.json"
    taken = {plan.path_key(base), plan.path_key("organized/data/json/undated/undated_x_3.json")}
    assert plan.nth_free(base, "json", taken, 1) == "organized/data/json/undated/undated_x_2.json"
    assert plan.nth_free(base, "json", taken, 2) == "organized/data/json/undated/undated_x_4.json"


def test_hash_prefixes_grow_until_every_content_differs() -> None:
    one = "a" * 12 + "0" * 52
    two = "a" * 12 + "1" * 52
    assert plan.hash_length([fact("x", one), fact("y", two)]) == 16
    assert plan.hash_length([fact("x", "b" * 64), fact("y", "c" * 64)]) == 12
