from __future__ import annotations

import dataclasses
import json
import shutil
from pathlib import Path

import pytest
from slimconfig import build_output, plain_output

import verifier
from contract import TOOLS, InventoryInput, Move, OrganizeInput, PinOutput, PlanInput, Tool
from plugin import rules
from plugin.organizer import apply_plan, inventory, list_tree, pin_inventory, read_rules, unpack_inbox

ARGUMENTS = {"seed": 1, "size": "small"}
ROOT = "file-organizer/1-small"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    folder = tmp_path / "workspace"
    folder.mkdir()
    unpack_inbox(build_output(ARGUMENTS, OrganizeInput), folder)
    return folder


@pytest.fixture
def reference(tmp_path: Path) -> dict:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    return plain_output(pin_inventory(build_output(ARGUMENTS, OrganizeInput), scratch))


# The verifier gets contract instances, as NanoAgent's sandbox builds them from JSON.
def verify_input(tool: str, value: dict) -> dict:
    return verifier.verify_input(tool, build_output(value, TOOLS[Tool(tool)][0]))


def verify_output(tool: str, value: dict, output: dict, workspace: Path) -> dict:
    given, made = TOOLS[Tool(tool)]
    return verifier.verify_output(tool, build_output(value, given), build_output(output, made), str(workspace))


def verify_task(reference: dict, workspace: Path, arguments: dict = ARGUMENTS) -> dict:
    return verifier.verify_task("organize", build_output(arguments, OrganizeInput), build_output(reference, PinOutput), str(workspace))


def pages(workspace: Path) -> list:
    files, offset = [], 0
    while offset is not None:
        page = inventory(InventoryInput(root=ROOT, offset=offset, limit=100), workspace)
        files += page.files
        offset = page.next
    return files


def listed(workspace: Path) -> list[rules.Row]:
    return [rules.Row(**{name: value for name, value in dataclasses.asdict(file).items() if name != "i"}) for file in pages(workspace)]


def numbers(workspace: Path) -> dict[str, int]:
    return {file.path: file.i for file in pages(workspace)}


def apply(workspace: Path, moves: list[tuple[str, str]], deletes: list[str]) -> None:
    """Apply a whole plan by file number, in batches of 80 moves and 80 deletes, as the tool takes them."""
    ids = numbers(workspace)
    for start in range(0, max(len(moves), len(deletes), 1), 80):
        batch = PlanInput(root=ROOT, moves=[Move(i=ids[src], dst=dst) for src, dst in moves[start : start + 80]], deletes=[ids[path] for path in deletes[start : start + 80]])
        outcome = apply_plan(batch, workspace)
        assert not outcome.errors, outcome.errors


def planned(workspace: Path) -> rules.Plan:
    return rules.plan(listed(workspace))


def test_approves_the_folder_tidied_by_the_rules(workspace: Path, reference: dict) -> None:
    plan = planned(workspace)
    apply(workspace, list(plan.moves), list(plan.deletes))
    verdict = verify_task(reference, workspace)
    assert verdict["valid"] is True and verdict["score"] == 1.0
    assert verdict["message"] == f"all {plan.unique} files are in place and nothing else remains"
    assert verdict["details"]["placed"] == plan.unique == reference["unique"]
    assert all(verdict["details"][key] == [] for key in ("missing", "misplaced", "duplicates_kept", "extra", "leftovers", "bad_names"))


def test_approves_the_plan_applied_in_two_batches_by_number(workspace: Path, reference: dict) -> None:
    """The hosted path: files numbered 0 to 29 first, then the rest; names were decided over all files."""
    plan = planned(workspace)
    ids = numbers(workspace)
    halves = [lambda number: number < 30, lambda number: number >= 30]
    for half in halves:
        moves = [Move(i=ids[src], dst=dst) for src, dst in plan.moves if half(ids[src])]
        deletes = [ids[path] for path in plan.deletes if half(ids[path])]
        outcome = apply_plan(PlanInput(root=ROOT, moves=moves, deletes=deletes), workspace)
        assert not outcome.errors, outcome.errors
    verdict = verify_task(reference, workspace)
    assert verdict["valid"] is True and verdict["score"] == 1.0


def test_refuses_an_untouched_folder_with_score_zero(workspace: Path, reference: dict) -> None:
    verdict = verify_task(reference, workspace)
    assert verdict["valid"] is False and verdict["score"] == 0.0
    assert len(verdict["details"]["missing"]) == reference["unique"] and len(verdict["details"]["leftovers"]) == 60
    assert "missing" in verdict["message"] and "left outside" in verdict["message"]


def test_refuses_duplicates_moved_instead_of_deleted(workspace: Path, reference: dict) -> None:
    rows = {row.path: row for row in listed(workspace)}
    plan = planned(workspace)
    kept = {digest for digest, _path in plan.expected}
    copies = [path for path in plan.deletes if rows[path].sha256 in kept]
    assert copies
    moves = list(plan.moves) + [(path, f"organized/duplicates/{index}-{rules.file_name(path)}") for index, path in enumerate(copies)]
    apply(workspace, moves, [path for path in plan.deletes if path not in copies])
    verdict = verify_task(reference, workspace)
    assert verdict["valid"] is False and verdict["score"] == 1.0
    assert "duplicate" in verdict["message"] and "not named by the rules" in verdict["message"]
    assert len(verdict["details"]["duplicates_kept"]) == len({rows[path].sha256 for path in copies})
    assert len(verdict["details"]["bad_names"]) == len(copies)


def test_refuses_a_near_duplicate_deleted_by_name_and_size(workspace: Path, reference: dict) -> None:
    rows = listed(workspace)
    plan = planned(workspace)
    seen: dict[tuple[str, int], rules.Row] = {}
    victims = []
    for row in rows:
        key = (rules.file_name(row.path), row.size)
        if key in seen and seen[key].sha256 != row.sha256 and row.size:
            victims.append(row.path)
        seen.setdefault(key, row)
    assert victims, "the folder holds near-duplicates"
    apply(workspace, [(src, dst) for src, dst in plan.moves if src not in victims], list(plan.deletes) + victims)
    verdict = verify_task(reference, workspace)
    assert verdict["valid"] is False and "missing" in verdict["message"]
    assert {item["expected"] for item in verdict["details"]["missing"]} == {dst for src, dst in plan.moves if src in victims}
    assert verdict["score"] == pytest.approx((plan.unique - len(victims)) / plan.unique)


def test_refuses_types_taken_from_the_extension(workspace: Path, reference: dict) -> None:
    rows = listed(workspace)
    plan = planned(workspace)
    wrong = []
    for row in rows:
        claimed = {"jpeg": "jpg", "htm": "html"}.get(row.ext.lower(), row.ext.lower())
        if row.size and not rules.is_junk(rules.file_name(row.path)) and claimed != row.type:
            wrong.append(rules.Row(**{**dataclasses.asdict(row), "type": claimed if claimed in rules.CATEGORIES else "bin"}))
    assert wrong, "the folder holds misnamed files"
    by_path = {row.path: row for row in rows}
    by_path.update({row.path: row for row in wrong})
    misplan = rules.plan(list(by_path.values()))
    apply(workspace, list(misplan.moves), list(misplan.deletes))
    verdict = verify_task(reference, workspace)
    assert verdict["valid"] is False and "misplaced" in verdict["message"]
    assert verdict["details"]["misplaced"] and not verdict["details"]["bad_names"], "ext typing gives rule-shaped names in the wrong place"
    assert verdict["score"] < 1.0 and plan.unique == misplan.unique


def test_refuses_the_wrong_copy_kept(workspace: Path, reference: dict) -> None:
    rows = listed(workspace)
    plan = planned(workspace)
    by_hash: dict[str, list[rules.Row]] = {}
    for row in rows:
        if row.size and not rules.is_junk(rules.file_name(row.path)):
            by_hash.setdefault(row.sha256, []).append(row)
    latest = {digest: max(group, key=lambda row: (row.mtime_utc, row.path)) for digest, group in by_hash.items() if len(group) > 1}
    changed = [latest[digest] for digest, group in by_hash.items() if digest in latest and rules.target(latest[digest]) != rules.target(min(group, key=lambda row: (row.mtime_utc, row.path)))]
    assert changed, "keeping the latest copy changes at least one final path"
    kept = [row for row in rows if row.sha256 not in latest or row.path == latest[row.sha256].path]
    misplan = rules.plan(kept)
    apply(workspace, list(misplan.moves), [row.path for row in rows if row.path not in {row.path for row in kept}])
    verdict = verify_task(reference, workspace)
    assert verdict["valid"] is False and "misplaced" in verdict["message"]
    assert len(verdict["details"]["misplaced"]) >= len(changed) and plan.unique == misplan.unique


def test_refuses_collisions_ordered_by_name(workspace: Path, reference: dict) -> None:
    rows = listed(workspace)
    plan = planned(workspace)
    kept = {src for src, _dst in plan.moves}
    taken: set[str] = set()
    moves = []
    for row in sorted((row for row in rows if row.path in kept), key=lambda row: row.path):
        base = rules.target(row)
        destination, number = base, 1
        while destination in taken:
            number += 1
            destination = rules.with_suffix(base, number)
        taken.add(destination)
        moves.append((row.path, destination))
    assert sorted(moves) != sorted(plan.moves), "naming by path order differs from the rules for this folder"
    apply(workspace, moves, list(plan.deletes))
    verdict = verify_task(reference, workspace)
    assert verdict["valid"] is False and "misplaced" in verdict["message"]


def test_refuses_junk_and_empty_files_kept(workspace: Path, reference: dict) -> None:
    rows = {row.path: row for row in listed(workspace)}
    plan = planned(workspace)
    junk = [path for path in plan.deletes if rules.is_junk(rules.file_name(path)) and rows[path].size]
    empty = [path for path in plan.deletes if rows[path].size == 0]
    assert junk and empty
    moves = list(plan.moves)
    moves += [(path, rules.target(rows[path])) for path in junk]
    moves += [(path, rules.with_suffix(rules.target(rows[path]), 9)) for path in empty]
    apply(workspace, moves, [path for path in plan.deletes if path not in junk and path not in empty])
    verdict = verify_task(reference, workspace)
    assert verdict["valid"] is False and verdict["score"] == 1.0
    assert "other file" in verdict["message"]
    assert len(verdict["details"]["extra"]) == len(junk) + len(empty)


def test_refuses_files_left_in_the_inbox(workspace: Path, reference: dict) -> None:
    plan = planned(workspace)
    apply(workspace, list(plan.moves)[:-3], list(plan.deletes))
    verdict = verify_task(reference, workspace)
    assert verdict["valid"] is False and "left outside" in verdict["message"]
    assert verdict["details"]["leftovers"] == sorted(src for src, _dst in plan.moves[-3:])
    assert verdict["score"] == pytest.approx((plan.unique - 3) / plan.unique)


def test_refuses_a_name_date_used_over_metadata(workspace: Path, reference: dict) -> None:
    rows = listed(workspace)
    plan = planned(workspace)
    kept = {src: dst for src, dst in plan.moves}
    moves = []
    for row in sorted((row for row in rows if row.path in kept), key=lambda row: (row.mtime_utc, row.path)):
        date = rules.name_date(rules.file_name(row.path)) or rules.embedded_date(row) or row.mtime_utc[:10]
        moves.append((row.path, f"organized/{rules.CATEGORIES[row.type]}/{date[:4]}/{date}_{rules.slug(rules.file_name(row.path))}.{row.type}"))
    taken: dict[str, int] = {}
    unique_moves = []
    for src, dst in moves:
        number = taken.get(dst, 0) + 1
        taken[dst] = number
        unique_moves.append((src, dst if number == 1 else rules.with_suffix(dst, number)))
    assert sorted(unique_moves) != sorted(plan.moves), "a name date disagrees with embedded metadata in this folder"
    apply(workspace, unique_moves, list(plan.deletes))
    verdict = verify_task(reference, workspace)
    assert verdict["valid"] is False and "misplaced" in verdict["message"]


def test_refuses_a_duplicate_kept_under_a_collision_suffix(workspace: Path, reference: dict) -> None:
    rows = {row.path: row for row in listed(workspace)}
    plan = planned(workspace)
    kept = {digest: path for digest, path in plan.expected}
    copy = next(path for path in plan.deletes if rows[path].sha256 in kept)
    moves = list(plan.moves) + [(copy, rules.with_suffix(kept[rows[copy].sha256], 7))]
    apply(workspace, moves, [path for path in plan.deletes if path != copy])
    verdict = verify_task(reference, workspace)
    assert verdict["valid"] is False and "1 duplicate kept" in verdict["message"]
    assert verdict["details"]["duplicates_kept"] == [{"sha256": rows[copy].sha256, "expected": kept[rows[copy].sha256], "extra": [rules.with_suffix(kept[rows[copy].sha256], 7)]}]


def test_refuses_a_pin_for_another_folder_and_a_missing_folder(tmp_path: Path, reference: dict) -> None:
    verdict = verify_task(reference, tmp_path, {"seed": 2, "size": "small"})
    assert verdict["valid"] is False and "another folder" in verdict["message"]
    verdict = verify_task(reference, tmp_path)
    assert verdict["valid"] is False and "never unpacked" in verdict["message"]


def test_checks_the_tools_inputs() -> None:
    assert verify_input("pin_inventory", ARGUMENTS)["valid"] is True
    assert verify_input("unpack_inbox", {"seed": -1, "size": "large"})["valid"] is False
    assert verify_input("unpack_inbox", {"seed": 10**9, "size": "large"})["valid"] is False
    assert verify_input("read_rules", {})["valid"] is True
    assert verify_input("inventory", {"root": ROOT, "offset": 0, "limit": 100})["valid"] is True
    assert verify_input("inventory", {"root": ROOT, "offset": 0, "limit": 101})["valid"] is False
    assert verify_input("inventory", {"root": ROOT, "offset": -1, "limit": 10})["valid"] is False
    assert verify_input("inventory", {"root": "file-organizer/1-tiny", "offset": 0, "limit": 10})["valid"] is False
    assert verify_input("inventory", {"root": "../" + ROOT, "offset": 0, "limit": 10})["valid"] is False
    good = {"root": ROOT, "moves": [{"i": 0, "dst": "organized/documents/txt/2020/2020-01-01_b.txt"}], "deletes": [1]}
    assert verify_input("apply_plan", good)["valid"] is True
    assert verify_input("apply_plan", {**good, "moves": [{"i": 0, "dst": "../b"}]})["valid"] is False
    assert verify_input("apply_plan", {**good, "moves": [{"i": 0, "dst": "/organized/b"}]})["valid"] is False
    assert verify_input("apply_plan", {**good, "moves": [{"i": 0, "dst": "inbox/b"}]})["valid"] is False
    assert verify_input("apply_plan", {**good, "moves": [{"i": 0, "dst": "organized/../b"}]})["valid"] is False
    assert verify_input("apply_plan", {**good, "moves": [{"i": 0, "dst": "organized/"}]})["valid"] is False
    assert verify_input("apply_plan", {**good, "moves": [{"i": -1, "dst": "organized/b"}]})["valid"] is False
    assert verify_input("apply_plan", {**good, "deletes": [-3]})["valid"] is False
    assert verify_input("apply_plan", {**good, "moves": [{"i": 0, "dst": "organized/b"}, {"i": 2, "dst": "organized/b"}]})["valid"] is False
    assert verify_input("apply_plan", {**good, "moves": [{"i": 0, "dst": "organized/b"}, {"i": 0, "dst": "organized/c"}]})["valid"] is False
    assert verify_input("apply_plan", {**good, "deletes": [0]})["valid"] is False
    many = [{"i": index, "dst": f"organized/{index}"} for index in range(100, 181)]
    assert verify_input("apply_plan", {**good, "moves": many})["valid"] is False
    assert verify_input("apply_plan", {**good, "moves": many[:80]})["valid"] is True
    assert verify_input("apply_plan", {**good, "deletes": list(range(200, 281))})["valid"] is False
    assert verify_input("list_tree", {"root": ROOT, "max_entries": 200})["valid"] is True
    assert verify_input("list_tree", {"root": ROOT, "max_entries": 0})["valid"] is False


def test_checks_the_tools_outputs(workspace: Path, tmp_path: Path, reference: dict) -> None:
    scratch = tmp_path / "scratch"
    assert verify_output("pin_inventory", ARGUMENTS, reference, scratch)["valid"] is True
    tampered = json.loads(json.dumps(reference))
    tampered["expected"][0]["path"] = tampered["expected"][0]["path"].replace("organized/", "organized/images/jpg/2020/2020-01-01_", 1)
    assert verify_output("pin_inventory", ARGUMENTS, tampered, scratch)["valid"] is False
    tampered = json.loads(json.dumps(reference))
    tampered["unique"] += 1
    assert verify_output("pin_inventory", ARGUMENTS, tampered, scratch)["valid"] is False
    assert verify_output("pin_inventory", {"seed": 2, "size": "small"}, reference, scratch)["valid"] is False

    rules_md = read_rules(build_output({}, TOOLS[Tool.READ_RULES][0]), workspace).rules
    unpacked = {"root": ROOT, "files": 60, "dirs": 9, "complete": False, "note": "made", "rules": rules_md}
    assert verify_output("unpack_inbox", ARGUMENTS, unpacked, workspace)["valid"] is True
    assert verify_output("unpack_inbox", ARGUMENTS, {**unpacked, "rules": "# nothing"}, workspace)["valid"] is False
    assert verify_output("unpack_inbox", ARGUMENTS, {**unpacked, "files": 59}, workspace)["valid"] is False
    assert verify_output("unpack_inbox", ARGUMENTS, {**unpacked, "root": "file-organizer/2-small"}, workspace)["valid"] is False
    assert verify_output("unpack_inbox", ARGUMENTS, {**unpacked, "complete": True}, workspace)["valid"] is True

    page_input = {"root": ROOT, "offset": 10, "limit": 20}
    page = plain_output(inventory(build_output(page_input, InventoryInput), workspace))
    assert verify_output("inventory", page_input, page, workspace)["valid"] is True
    wrong = json.loads(json.dumps(page))
    wrong["files"][0]["mtime_utc"] = "2000-01-01T00:00:00Z"
    assert verify_output("inventory", page_input, wrong, workspace)["valid"] is False
    wrong = json.loads(json.dumps(page))
    wrong["next"] = None
    assert verify_output("inventory", page_input, wrong, workspace)["valid"] is False

    rules_text = plain_output(read_rules(build_output({}, TOOLS[Tool.READ_RULES][0]), workspace))
    assert verify_output("read_rules", {}, rules_text, workspace)["valid"] is True
    assert verify_output("read_rules", {}, {"rules": "# nothing"}, workspace)["valid"] is False

    plan = planned(workspace)
    ids = numbers(workspace)
    src, dst = plan.moves[0]
    plan_input = {"root": ROOT, "moves": [{"i": ids[src], "dst": dst}], "deletes": [ids[plan.deletes[0]]]}
    outcome = plain_output(apply_plan(build_output(plan_input, PlanInput), workspace))
    assert outcome["errors"] == []
    assert verify_output("apply_plan", plan_input, outcome, workspace)["valid"] is True
    assert verify_output("apply_plan", plan_input, {**outcome, "moved": 0}, workspace)["valid"] is False
    again = {"root": ROOT, "moves": [{"i": 99999, "dst": "organized/x.txt"}], "deletes": [ids[plan.deletes[0]]]}
    assert verify_output("apply_plan", again, {"moved": 1, "deleted": 1, "removed_dirs": 0, "errors": []}, workspace)["valid"] is False
    errors = ["move 99999 -> organized/x.txt: unknown number: not in the inventory", f"delete {ids[plan.deletes[0]]}: already deleted"]
    assert verify_output("apply_plan", again, {"moved": 0, "deleted": 0, "removed_dirs": 0, "errors": errors}, workspace)["valid"] is True
    assert verify_output("unpack_inbox", ARGUMENTS, {**unpacked, "files": 58, "complete": True}, workspace)["valid"] is True
    assert verify_output("unpack_inbox", ARGUMENTS, {**unpacked, "files": 58, "complete": False}, workspace)["valid"] is False
    assert verify_output("unpack_inbox", ARGUMENTS, {**unpacked, "files": 60, "complete": True}, workspace)["valid"] is False

    tree_input = {"root": ROOT, "max_entries": 50}
    tree = plain_output(list_tree(build_output(tree_input, TOOLS[Tool.LIST_TREE][0]), workspace))
    assert verify_output("list_tree", tree_input, tree, workspace)["valid"] is True
    assert verify_output("list_tree", tree_input, {**tree, "entries": list(reversed(tree["entries"]))}, workspace)["valid"] is False
    assert verify_output("list_tree", tree_input, {**tree, "files": 61}, workspace)["valid"] is False


def test_the_verdict_is_the_same_twice(workspace: Path, reference: dict) -> None:
    plan = planned(workspace)
    apply(workspace, list(plan.moves)[:-2], list(plan.deletes)[:-1])
    first = verify_task(reference, workspace)
    second = verify_task(reference, workspace)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    shutil.rmtree(workspace / ROOT / "organized")
    assert verify_task(reference, workspace)["details"]["placed"] == 0
