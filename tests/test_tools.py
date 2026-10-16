"""The tools on real folders: pin_layout, survey and apply, their refusals and the run's state."""

from __future__ import annotations

import json
import os
from pathlib import Path

import builders
import pytest
from messy import messy, unpack

from contract import ApplyInput, Drop, Move, OrganizeInput
from plugin import organizer


@pytest.fixture(autouse=True)
def fresh_run():
    organizer.RUN = None
    yield
    organizer.RUN = None


def folder(tmp_path: Path, files: dict[str, bytes]) -> Path:
    unpack(files, tmp_path)
    return tmp_path


def small(tmp_path: Path) -> Path:
    return folder(
        tmp_path,
        {
            "Downloads/IMG_1.jpg": builders.jpeg(1, "2019-07-14"),
            "Downloads/sub/IMG_1 copy.jpg": builders.jpeg(1, "2019-07-14"),
            "Downloads/notes.txt": b"hello\n",
            "Downloads/sub/notes.txt": b"other\n",
            "Downloads/.DS_Store": b"\x00\x00\x00\x01Bud1",
            "Downloads/empty.md": b"",
            "Downloads/.git/HEAD": b"ref\n",
            "Notes/outside.txt": b"keep\n",
        },
    )


def test_pin_layout_pins_every_file_in_order(tmp_path: Path) -> None:
    pin = organizer.pin_layout(OrganizeInput(folder="Downloads"), small(tmp_path))
    assert [file.i for file in pin.files] == list(range(6))
    assert {file.path for file in pin.files} == {"IMG_1.jpg", "sub/IMG_1 copy.jpg", "notes.txt", "sub/notes.txt", ".DS_Store", "empty.md"}
    by_path = {file.path: file for file in pin.files}
    assert by_path["IMG_1.jpg"].target == "organized/images/jpg/2019/2019-07-14_img-1.jpg"
    assert by_path["sub/IMG_1 copy.jpg"].reason.value == "copy"
    assert by_path["sub/notes.txt"].target == "organized/documents/txt/undated/undated_notes_2.txt"
    assert (pin.pending, pin.quota) == (6, 6)
    assert not (tmp_path / ".file-organizer").exists()  # the reference writes nothing


def test_survey_rows_and_summary(tmp_path: Path) -> None:
    out = organizer.survey(OrganizeInput(folder="Downloads"), small(tmp_path))
    rows = {row.path: row for row in out.rows}
    assert rows[".DS_Store"].drop is Drop.JUNK and rows[".DS_Store"].base is None
    assert rows["empty.md"].drop is Drop.EMPTY
    assert rows["sub/IMG_1 copy.jpg"].drop is None and rows["sub/IMG_1 copy.jpg"].h == rows["IMG_1.jpg"].h  # its keeper is a row
    assert all(len(row.h) == 12 for row in out.rows)
    assert out.summary.left == 6 and out.summary.moved == 0
    assert "6 files take part" in out.note
    state = json.loads((tmp_path / ".file-organizer" / "state.json").read_text())
    assert state["folder"] == "Downloads" and len(state["rows"]) == 6 and state["applied"] == []
    again = organizer.survey(OrganizeInput(folder="Downloads"), tmp_path)
    assert again.rows == out.rows
    with pytest.raises(ValueError, match="this run organizes Downloads"):
        organizer.survey(OrganizeInput(folder="Notes"), tmp_path)


def test_a_copy_of_a_file_in_place_is_dropped(tmp_path: Path) -> None:
    data = builders.jpeg(2, "2018-01-02")
    workspace = folder(tmp_path, {"P/organized/images/jpg/2018/2018-01-02_x.jpg": data, "P/dup.jpg": data, "P/new.txt": b"n\n"})
    out = organizer.survey(OrganizeInput(folder="P"), workspace)
    rows = {row.path: row for row in out.rows}
    assert rows["dup.jpg"].drop is Drop.COPY and out.summary.stayed == 1


def test_apply_deletes_then_moves_and_reports_refusals(tmp_path: Path) -> None:
    workspace = small(tmp_path)
    out = organizer.survey(OrganizeInput(folder="Downloads"), workspace)
    i = {row.path: row.i for row in out.rows}
    done = organizer.apply(
        ApplyInput(
            folder="Downloads",
            moves=[Move(i=i["IMG_1.jpg"], n=1), Move(i=i["notes.txt"], n=1), Move(i=i["sub/notes.txt"], n=1), Move(i=i[".DS_Store"], n=1), Move(i=99, n=1)],
            deletes=[i["sub/IMG_1 copy.jpg"], i["empty.md"]],
        ),
        workspace,
    )
    assert done.applied == 4
    assert any(error.startswith(f"move {i['sub/notes.txt']}:") and "already taken" in error for error in done.errors)
    assert any(error.startswith(f"move {i['.DS_Store']}:") and "never moved" in error for error in done.errors)
    assert any(error.startswith("move 99:") and "not one of this run's rows" in error for error in done.errors)
    assert (workspace / "Downloads/organized/images/jpg/2019/2019-07-14_img-1.jpg").is_file()
    assert not (workspace / "Downloads/sub/IMG_1 copy.jpg").exists() and (workspace / "Downloads/sub/notes.txt").exists()
    again = organizer.apply(ApplyInput(folder="Downloads", moves=[Move(i=i["sub/notes.txt"], n=2)], deletes=[i[".DS_Store"]]), workspace)
    assert again.applied == 2 and not again.errors
    assert again.summary.left == 0 and again.summary.moved == 3 and again.summary.deleted == 3
    assert not (workspace / "Downloads/sub").exists()  # pruned once empty
    assert (workspace / "Downloads/.git/HEAD").read_bytes() == b"ref\n"


def test_apply_never_deletes_the_last_copy(tmp_path: Path) -> None:
    workspace = small(tmp_path)
    out = organizer.survey(OrganizeInput(folder="Downloads"), workspace)
    i = {row.path: row.i for row in out.rows}
    first = organizer.apply(ApplyInput(folder="Downloads", moves=[], deletes=[i["IMG_1.jpg"], i["sub/IMG_1 copy.jpg"], i["notes.txt"]]), workspace)
    assert first.applied == 1
    assert any("only copy of its bytes" in error for error in first.errors)
    assert (workspace / "Downloads/sub/IMG_1 copy.jpg").exists() and (workspace / "Downloads/notes.txt").exists()


def test_apply_checks_the_bytes_before_acting(tmp_path: Path) -> None:
    workspace = small(tmp_path)
    out = organizer.survey(OrganizeInput(folder="Downloads"), workspace)
    i = {row.path: row.i for row in out.rows}
    (workspace / "Downloads/notes.txt").write_bytes(b"changed\n")
    done = organizer.apply(ApplyInput(folder="Downloads", moves=[Move(i=i["notes.txt"], n=1)], deletes=[]), workspace)
    assert done.applied == 0 and "changed or unreadable since survey" in done.errors[0]


def test_apply_needs_a_survey_of_this_run(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="call survey"):
        organizer.apply(ApplyInput(folder="Downloads", moves=[], deletes=[]), small(tmp_path))


@pytest.mark.parametrize(
    ("name", "message"),
    [("Missing", "No folder Missing"), (".git", "hidden"), ("x/organized", "inside an organized/ folder"), ("../up", "relative path"), ("a\\b", "relative path"), ("a//b", "relative path")],
)
def test_folders_the_task_cannot_name(tmp_path: Path, name: str, message: str) -> None:
    small(tmp_path)
    with pytest.raises(ValueError, match=message):
        organizer.pin_layout(OrganizeInput(folder=name), tmp_path)


def test_a_missing_folder_lists_the_agent_folder(tmp_path: Path) -> None:
    small(tmp_path)
    with pytest.raises(ValueError, match=r"Downloads/, Notes/"):
        organizer.survey(OrganizeInput(folder="Downloads2"), tmp_path)


def test_refusals_name_what_to_fix(tmp_path: Path) -> None:
    cases = {
        "nothing": ({"F/.hidden": b"x"}, "holds no files"),
        "symlink": ({"F/a.txt": b"x"}, "is a symlink"),
        "big": ({"F/big.bin": b"\0" * (10 * 1024 * 1024 + 1)}, "over the 10 MiB"),
        "deep": ({"F/" + "/".join("d" * 13) + "/x.txt": b"x"}, "deeper than 12"),
        "long": ({"F/" + "n" * 250 + "/" + "m" * 60 + ".txt": b"x"}, "longer than 300"),
        "case": ({"F/organized/Images/jpg/2019/a.txt": b"x", "F/new.jpg": builders.jpeg(1, "2019-01-01")}, "only in letter case"),
        "as_file": ({"F/organized/images": b"x", "F/new.jpg": builders.jpeg(1, "2019-01-01")}, "is a file, but the rules need a folder"),
    }
    for label, (files, message) in cases.items():
        root = tmp_path / label
        root.mkdir()
        unpack(files, root)
        if label == "symlink":
            os.symlink(root / "F" / "a.txt", root / "F" / "link.txt")
        organizer.RUN = None
        with pytest.raises(ValueError, match=message):
            organizer.survey(OrganizeInput(folder="F"), root)


def test_too_many_files_and_too_many_entries(tmp_path: Path) -> None:
    many = tmp_path / "many"
    unpack({f"F/f{index}.txt": f"{index}".encode() for index in range(1001)}, many)
    with pytest.raises(ValueError, match="1001 files take part"):
        organizer.pin_layout(OrganizeInput(folder="F"), many)
    crowded = tmp_path / "crowded"
    # 1 + 4,895 entries outside, the folder, 4 new folders and 2 files inside, 2 for the state: 4,905
    unpack({**{f"Other/o{index}.txt": b"x" for index in range(4895)}, "F/a.txt": b"a", "F/b.txt": b"b"}, crowded)
    with pytest.raises(ValueError, match="RUSH Lab saves at most 5,000"):
        organizer.pin_layout(OrganizeInput(folder="F"), crowded)


def test_the_whole_agent_folder_skips_the_plugin_state(tmp_path: Path) -> None:
    unpack(messy(5, "small", "."), tmp_path)
    out = organizer.survey(OrganizeInput(folder="."), tmp_path)
    assert all(not row.path.startswith(".file-organizer") for row in out.rows)
    organizer.RUN = None
    pin = organizer.pin_layout(OrganizeInput(folder="."), tmp_path)
    assert all(not file.path.startswith(".file-organizer") for file in pin.files)
