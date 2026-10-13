from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path

import pytest

from contract import InventoryInput, Move, OrganizeInput, PlanInput, RulesInput, Size, TreeInput
from plugin import organizer, rules
from plugin.common import confine
from plugin.organizer import apply_plan, inventory, list_tree, pin_inventory, read_rules, unpack_inbox

SMALL = OrganizeInput(seed=1, size=Size.SMALL)
ROOT = "file-organizer/1-small"
LEDGER = "file-organizer/1-small.ids.json"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    unpack_inbox(SMALL, tmp_path)
    return tmp_path


def rows(workspace: Path) -> list[rules.Row]:
    return rules.inventory_rows(workspace / ROOT)


def as_row(file) -> rules.Row:
    return rules.Row(**{name: value for name, value in dataclasses.asdict(file).items() if name != "i"})


def numbers(workspace: Path) -> dict[str, int]:
    """Each file's number by its current path, from a full inventory."""
    found: dict[str, int] = {}
    offset: int | None = 0
    while offset is not None:
        page = inventory(InventoryInput(root=ROOT, offset=offset, limit=100), workspace)
        found.update({file.path: file.i for file in page.files})
        offset = page.next
    return found


def test_unpack_makes_the_folder_once_and_never_destroys_progress(tmp_path: Path) -> None:
    made = unpack_inbox(SMALL, tmp_path)
    assert made.root == ROOT and made.files == 45 and 8 <= made.dirs <= 25 and made.complete is False
    assert made.rules == read_rules(RulesInput(), tmp_path).rules
    assert made.inventory == inventory(InventoryInput(root=ROOT, offset=0, limit=100), tmp_path), "the first inventory page comes with the folder"
    assert made.inventory.total == 45 and made.inventory.next is None and [file.i for file in made.inventory.files] == list(range(45))
    assert (tmp_path / ROOT / "inbox").is_dir() and (tmp_path / ROOT / "organized").is_dir()
    before = [(row.path, row.sha256, row.mtime_utc) for row in rows(tmp_path)]
    assert unpack_inbox(SMALL, tmp_path) == made, "an untouched folder gives the same answer again"
    assert [(row.path, row.sha256, row.mtime_utc) for row in rows(tmp_path)] == before
    ids = numbers(tmp_path)
    planned = rules.plan(rows(tmp_path))
    src, dst = planned.moves[0]
    apply_plan(PlanInput(root=ROOT, moves=[Move(i=ids[src], dst=dst)], deletes=[ids[planned.deletes[0]]]), tmp_path)
    after = [(row.path, row.sha256, row.mtime_utc) for row in rows(tmp_path)]
    again = unpack_inbox(SMALL, tmp_path)
    assert again.complete is True and again.files == 43 and "nothing was changed" in again.note
    assert again.inventory.total == 44, "the page lists the moved file under organized/ too"
    assert {file.i for file in again.inventory.files} == set(range(45)) - {ids[planned.deletes[0]]}
    assert [(row.path, row.sha256, row.mtime_utc) for row in rows(tmp_path)] == after, "a worked-on folder is left as it is"
    for path in (tmp_path / ROOT).rglob("*"):
        if path.is_file():
            path.unlink()
    fresh = unpack_inbox(SMALL, tmp_path)
    assert fresh == made and [(row.path, row.sha256, row.mtime_utc) for row in rows(tmp_path)] == before, "a folder without files is made again"
    assert list(numbers(tmp_path).values()) == list(range(45)), "the numbers start over with the folder"
    with pytest.raises(ValueError, match="never made over"):
        pin_inventory(SMALL, tmp_path)


def test_read_rules_returns_the_document(tmp_path: Path) -> None:
    text = read_rules(RulesInput(), tmp_path).rules
    assert text == (Path(__file__).resolve().parents[1] / "src" / "plugin" / "RULES.md").read_text(encoding="utf-8")
    assert "## 5. Collisions" in text


def test_inventory_pages_in_path_order_and_numbers_files(workspace: Path) -> None:
    first = inventory(InventoryInput(root=ROOT, offset=0, limit=30), workspace)
    second = inventory(InventoryInput(root=ROOT, offset=30, limit=30), workspace)
    assert (first.total, first.next, len(first.files)) == (45, 30, 30)
    assert (second.total, second.next, len(second.files)) == (45, None, 15)
    listed = first.files + second.files
    assert [as_row(file) for file in listed] == rows(workspace)
    assert [file.path for file in listed] == sorted(file.path for file in listed)
    assert [file.i for file in listed] == list(range(45)), "a fresh folder is numbered in path order"
    assert json.loads((workspace / LEDGER).read_text())["files"]["0"] == listed[0].path
    assert inventory(InventoryInput(root=ROOT, offset=500, limit=10), workspace).files == []
    with pytest.raises(ValueError, match="limit"):
        inventory(InventoryInput(root=ROOT, offset=0, limit=101), workspace)
    whole = inventory(InventoryInput(root=ROOT, offset=0, limit=100), workspace)
    assert len(whole.files) == 45 and whole.next is None
    with pytest.raises(FileNotFoundError, match="unpack_inbox"):
        inventory(InventoryInput(root="file-organizer/2-small", offset=0, limit=10), workspace)
    with pytest.raises(ValueError, match="root must be"):
        inventory(InventoryInput(root="../x", offset=0, limit=10), workspace)


def test_inventory_reports_raw_metadata_and_mtimes(workspace: Path) -> None:
    listed = rows(workspace)
    assert any(row.exif and ":" in row.exif[:10] for row in listed), "EXIF dates stay in their colon form"
    for row in listed:
        stat = (workspace / ROOT / row.path).stat()
        assert row.mtime_utc == rules.utc_stamp(stat.st_mtime_ns // 1_000_000_000) and row.size == stat.st_size


def test_numbers_stay_with_files_across_moves_deletes_and_processes(workspace: Path) -> None:
    ids = numbers(workspace)
    planned = rules.plan(rows(workspace))
    src, dst = planned.moves[0]
    gone = planned.deletes[0]
    outcome = apply_plan(PlanInput(root=ROOT, moves=[Move(i=ids[src], dst=dst)], deletes=[ids[gone]]), workspace)
    assert (outcome.moved, outcome.deleted, outcome.errors) == (1, 1, [])
    after = numbers(workspace)
    assert after[dst] == ids[src], "a moved file keeps its number"
    assert {path: number for path, number in after.items() if path != dst} == {path: number for path, number in ids.items() if path not in (src, gone)}
    record = json.loads((workspace / LEDGER).read_text())
    assert record["files"][str(ids[src])] == dst and record["deleted"] == {str(ids[gone]): gone}
    organizer.LEDGERS.clear()  # a new plugin process reads the record back
    assert numbers(workspace) == after
    again = apply_plan(PlanInput(root=ROOT, moves=[Move(i=ids[gone], dst="organized/x.txt"), Move(i=424242, dst="organized/y.txt")], deletes=[ids[gone], 424243]), workspace)
    assert (again.moved, again.deleted) == (0, 0)
    assert again.errors == [
        f"move {ids[gone]} -> organized/x.txt: already deleted",
        "move 424242 -> organized/y.txt: unknown number: not in the inventory",
        f"delete {ids[gone]}: already deleted",
        "delete 424243: unknown number: not in the inventory",
    ]
    moved_again = apply_plan(PlanInput(root=ROOT, moves=[Move(i=ids[src], dst="organized/documents/txt/2000/2000-01-01_again.txt")], deletes=[]), workspace)
    assert moved_again.moved == 1 and numbers(workspace)["organized/documents/txt/2000/2000-01-01_again.txt"] == ids[src], "a moved file can be moved again by its number"


def test_apply_plan_moves_deletes_prunes_and_reports_each_failure(workspace: Path) -> None:
    ids = numbers(workspace)
    planned = rules.plan(rows(workspace))
    src, dst = planned.moves[0]
    others = [ids[source] for source, _destination in planned.moves[1:7]]
    (workspace / ROOT / "inbox" / "Empty folder" / "deeper").mkdir(parents=True)
    outcome = apply_plan(
        PlanInput(
            root=ROOT,
            moves=[
                Move(i=ids[src], dst=dst),
                Move(i=ids[src], dst=dst),  # onto itself: the destination exists
                Move(i=others[0], dst=dst),  # taken
                Move(i=others[1], dst="inbox/elsewhere.txt"),  # not under organized/
                Move(i=others[2], dst="organized/../escape.txt"),
                Move(i=others[3], dst=dst + "/x"),  # through a file
                Move(i=99999, dst="organized/x.txt"),
            ],
            deletes=[ids[planned.deletes[0]], ids[planned.deletes[0]], 99998],
        ),
        workspace,
    )
    assert (outcome.moved, outcome.deleted) == (1, 1)
    assert (workspace / ROOT / dst).is_file() and not (workspace / ROOT / src).exists()
    assert not (workspace / ROOT / planned.deletes[0]).exists()
    assert not (workspace / ROOT / "inbox" / "Empty folder").exists() and outcome.removed_dirs >= 2
    assert (workspace / ROOT / "inbox").is_dir()
    assert len(outcome.errors) == 8
    assert outcome.errors[0] == f"move {ids[src]} -> {dst}: the destination exists"
    assert outcome.errors[1] == f"move {others[0]} -> {dst}: the destination exists"
    assert "must be a file path under organized/" in outcome.errors[2]
    assert "must stay inside" in outcome.errors[3]
    assert outcome.errors[4].startswith(f"move {others[3]} -> {dst}/x: ")
    assert outcome.errors[5] == "move 99999 -> organized/x.txt: unknown number: not in the inventory"
    assert outcome.errors[6] == f"delete {ids[planned.deletes[0]]}: already deleted"
    assert outcome.errors[7] == "delete 99998: unknown number: not in the inventory"
    assert not any("/Users" in line or str(workspace) in line for line in outcome.errors), "no absolute paths in outputs"


def test_apply_plan_takes_at_most_eighty_moves_and_deletes(workspace: Path) -> None:
    ids = numbers(workspace)
    planned = rules.plan(rows(workspace))
    too_many = [Move(i=index, dst=f"organized/{index}.txt") for index in range(81)]
    with pytest.raises(ValueError, match="batches"):
        apply_plan(PlanInput(root=ROOT, moves=too_many, deletes=[]), workspace)
    with pytest.raises(ValueError, match="batches"):
        apply_plan(PlanInput(root=ROOT, moves=[], deletes=list(range(81))), workspace)
    assert len(planned.moves) <= 80 and len(planned.deletes) <= 80, "a small folder's whole plan fits one call"
    outcome = apply_plan(PlanInput(root=ROOT, moves=[Move(i=ids[src], dst=dst) for src, dst in planned.moves], deletes=[ids[path] for path in planned.deletes]), workspace)
    assert (outcome.moved, outcome.deleted, outcome.errors) == (len(planned.moves), len(planned.deletes), [])
    assert not [path for path in (workspace / ROOT / "inbox").rglob("*") if path.is_file()]


def test_apply_plan_refuses_symlinks(workspace: Path) -> None:
    outside = workspace / "outside.txt"
    outside.write_text("secret")
    (workspace / ROOT / "inbox" / "link.txt").symlink_to(outside)
    (workspace / ROOT / "organized" / "door").symlink_to(workspace, target_is_directory=True)
    ids = numbers(workspace)
    assert "inbox/link.txt" not in ids and not any(path.startswith("organized/door") for path in ids), "symlinks are never listed"
    first = next(iter(ids.values()))
    outcome = apply_plan(PlanInput(root=ROOT, moves=[Move(i=first, dst="organized/door/x.txt")], deletes=[]), workspace)
    assert outcome.moved == 0 and "must stay inside" in outcome.errors[0]
    assert outside.read_text() == "secret" and not (workspace / "x.txt").exists()


def test_list_tree_is_sorted_and_bounded(workspace: Path) -> None:
    tree = list_tree(TreeInput(root=ROOT, max_entries=200), workspace)
    assert tree.files == 45 and tree.entries == sorted(tree.entries) and not tree.truncated
    assert "inbox/" in tree.entries and "organized/" in tree.entries
    short = list_tree(TreeInput(root=ROOT, max_entries=5), workspace)
    assert len(short.entries) == 5 and short.truncated and short.files == 45
    with pytest.raises(ValueError, match="max_entries"):
        list_tree(TreeInput(root=ROOT, max_entries=201), workspace)


def test_pin_inventory_is_the_rules_applied_to_the_folder(tmp_path: Path) -> None:
    pinned = pin_inventory(SMALL, tmp_path)
    planned = rules.plan(rows(tmp_path))
    assert [(row.sha256, row.path) for row in pinned.expected] == list(planned.expected)
    assert (pinned.unique, pinned.duplicates, pinned.removed, pinned.files) == (planned.unique, planned.duplicates, planned.removed, 45)
    assert pinned.root == ROOT and pinned.size is Size.SMALL


def test_confine(tmp_path: Path) -> None:
    folder, outside = tmp_path / "folder", tmp_path / "outside"
    folder.mkdir()
    outside.mkdir()
    assert confine(folder, "a/b.txt") == folder.resolve() / "a" / "b.txt"
    for bad in ["", "/etc/passwd", "../x", "a/../../x", ".judge/x", "a\x00b"]:
        with pytest.raises(ValueError):
            confine(folder, bad)
    (folder / "door").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        confine(folder, "door/x")


def test_moved_files_keep_their_mtimes(workspace: Path) -> None:
    ids = numbers(workspace)
    planned = rules.plan(rows(workspace))
    src, dst = planned.moves[0]
    before = os.stat(workspace / ROOT / src).st_mtime_ns
    apply_plan(PlanInput(root=ROOT, moves=[Move(i=ids[src], dst=dst)], deletes=[]), workspace)
    assert os.stat(workspace / ROOT / dst).st_mtime_ns == before
