"""The challenger's review (FO-01 to FO-17), one scenario or more per finding: what broke, now handled as
RULES.md says. Scripted, end-to-end versions of the tampering scenarios are the wrong_* cases."""

from __future__ import annotations

import json
import shutil
import struct
import sys
import time
from pathlib import Path

import builders
import pytest
from flow import failed, host_run, judge
from messy import unpack
from oracle.oracle import facts as oracle_facts

from contract import OrganizeInput, OrganizeOutput
from plugin import organizer
from plugin.layout import look
from plugin.plan import ordered
from plugin.sniff import is_json
from plugin.walk import count_below, describe

FOLDER = "Downloads"
CANON = builders.jpeg(7, "2003-12-04")


@pytest.fixture(autouse=True)
def fresh_run():
    organizer.RUN = None
    yield
    organizer.RUN = None


def base_folder() -> dict[str, bytes]:
    """The red team's folder: a duplicate, junk, hidden entries in and below the folder, files outside it."""
    return {
        "Downloads/photos/Canon.jpg": CANON,
        "Downloads/photos/Canon copy.jpg": CANON,
        "Downloads/photos/Thumbs.db": b"\xd0\xcf\x11\xe0junk",
        "Downloads/report.pdf": builders.pdf(1, "2005-07-18"),
        "Downloads/notes.txt": b"some notes\n",
        "Downloads/.git/config": b"[core]\n",
        "Downloads/.vscode/settings.json": b"{}\n",
        "Downloads/old/.keep": b"",
        "Documents/keep-me.txt": b"keep me\n",
        "Documents/taxes.pdf": builders.pdf(2, "2020-04-01"),
    }


def kind(name: str, data: bytes) -> str:
    fact = describe(name, data)
    return f"{fact.group}/{fact.type}/{fact.ext}"


def after(tmp_path: Path, tamper, files: dict[str, bytes] | None = None, folder: str = FOLDER) -> dict:
    workspace, reference, output = host_run(tmp_path, files or base_folder(), folder)
    changed = tamper(workspace, output)
    return judge(workspace, reference, changed if isinstance(changed, OrganizeOutput) else output, folder)


# ----- FO-01: hidden entries in the folder are snapshotted -----


def hidden_deleted(workspace, _output):
    (workspace / "Downloads/.git/config").unlink()


def hidden_modified(workspace, _output):
    (workspace / "Downloads/.vscode/settings.json").write_text('{"tampered": true}')


def hidden_stray_copy(workspace, _output):
    (workspace / "Downloads/.backup-canon.jpg").write_bytes(CANON)


def duplicate_hidden(workspace, _output):
    (workspace / "Downloads/.Canon copy.jpg").write_bytes(CANON)  # the duplicate, renamed instead of deleted


def duplicate_into_hidden_folder(workspace, _output):
    (workspace / "Downloads/.trash").mkdir()
    (workspace / "Downloads/.trash/Canon copy.jpg").write_bytes(CANON)


def junk_hidden(workspace, _output):
    (workspace / "Downloads/.Thumbs-kept.db").write_bytes(b"\xd0\xcf\x11\xe0junk")


def hidden_fifo(workspace, _output):
    import os

    os.mkfifo(workspace / "Downloads/.pipe")


@pytest.mark.parametrize("tamper", [hidden_deleted, hidden_modified, hidden_stray_copy, duplicate_hidden, duplicate_into_hidden_folder, junk_hidden])
def test_fo01_hidden_entries_must_stay_as_they_were(tmp_path: Path, tamper) -> None:
    verdict = after(tmp_path, tamper)
    assert not verdict["valid"] and verdict["score"] < 1.0
    assert failed(verdict) == ["hidden-untouched"], verdict["message"]


def test_fo01_a_hidden_fifo_is_refused_not_ignored(tmp_path: Path) -> None:
    verdict = after(tmp_path, hidden_fifo)
    assert not verdict["valid"] and verdict["score"] == 0.0
    assert "Downloads/.pipe is not a regular file or folder" in verdict["message"]


def test_fo01_the_pin_lists_the_hidden_entries(tmp_path: Path) -> None:
    unpack(base_folder(), tmp_path)
    pin = organizer.pin_layout(OrganizeInput(folder=FOLDER), tmp_path)
    hidden = [entry.path for entry in pin.kept if entry.path.startswith("Downloads/")]
    assert hidden == ["Downloads/.git", "Downloads/.git/config", "Downloads/.vscode", "Downloads/.vscode/settings.json", "Downloads/old/.keep"]
    assert all((entry.sha256 is None) == entry.folder for entry in pin.kept)


# ----- FO-02: everything outside the folder is snapshotted -----


def outside_deleted(workspace, _output):
    (workspace / "Documents/keep-me.txt").unlink()


def outside_modified(workspace, _output):
    (workspace / "Documents/taxes.pdf").write_bytes(b"%PDF-1.4 wiped")


def duplicate_moved_outside(workspace, _output):
    (workspace / "Elsewhere").mkdir()
    (workspace / "Elsewhere/Canon copy.jpg").write_bytes(CANON)


def hard_link_outside(workspace, _output):
    target = next((workspace / "Downloads/organized/documents/pdf").rglob("*.pdf"))
    (workspace / "report-link.pdf").hardlink_to(target)


def stash_in_state_folder(workspace, _output):
    (workspace / ".file-organizer/Canon copy.jpg").write_bytes(CANON)


@pytest.mark.parametrize("tamper", [outside_deleted, outside_modified, duplicate_moved_outside, hard_link_outside, stash_in_state_folder])
def test_fo02_everything_outside_the_folder_must_stay_as_it_was(tmp_path: Path, tamper) -> None:
    verdict = after(tmp_path, tamper)
    assert not verdict["valid"] and verdict["score"] < 1.0
    assert failed(verdict) == ["outside-untouched"], verdict["message"]


def state_deleted(workspace, _output):
    (workspace / ".file-organizer/state.json").unlink()


def state_rewritten(workspace, _output):
    path = workspace / ".file-organizer/state.json"
    state = json.loads(path.read_text())
    state["applied"], state["rows"] = [], []
    path.write_text(json.dumps(state))


@pytest.mark.parametrize("tamper", [state_deleted, state_rewritten])
def test_fo02_the_run_state_is_the_one_exception(tmp_path: Path, tamper) -> None:
    verdict = after(tmp_path, tamper)
    assert verdict["valid"] and verdict["score"] == 1.0, verdict["message"]


# ----- R2-01: the exemption is a regular state.json holding the run state, nothing else -----


def duplicate_onto_state(workspace, output):
    (workspace / ".file-organizer/state.json").write_bytes(CANON)  # the duplicate kept, under the state's name


def state_not_a_run_state(workspace, _output):
    (workspace / ".file-organizer/state.json").write_text("{}")


STATE_REFUSED = ".file-organizer/state.json is not this plugin's run state: rename or remove it, then ask again"


@pytest.mark.parametrize("tamper", [duplicate_onto_state, state_not_a_run_state])
def test_r2_01_state_json_must_hold_the_run_state(tmp_path: Path, tamper) -> None:
    verdict = after(tmp_path, tamper)
    assert failed(verdict) == ["plain-entries"] and verdict["score"] == 0.0 and STATE_REFUSED in verdict["message"]
    files = {path.removeprefix("Downloads/"): data for path, data in base_folder().items()}
    whole = after(tmp_path / "whole", tamper, files, ".")
    assert failed(whole) == ["plain-entries"] and STATE_REFUSED in whole["message"]


def state_replaced_by_folder(workspace, _output):
    import os

    state = workspace / ".file-organizer/state.json"
    state.unlink()
    (state / "stash").mkdir(parents=True)
    (state / "stash/Canon copy.jpg").write_bytes(CANON)
    (state / "stash/etc-link").symlink_to("/etc")
    os.mkfifo(state / "pipe")


def state_sibling(workspace, _output):
    (workspace / ".file-organizer/state.json.bak").write_text("x")


def test_r2_01_a_folder_or_a_sibling_at_the_state_path_fails(tmp_path: Path) -> None:
    folder = after(tmp_path / "folder", state_replaced_by_folder)
    assert folder["score"] == 0.0 and failed(folder) == ["plain-entries"]
    assert ".file-organizer/state.json is not a regular file, but the plugin keeps its run state there" in folder["message"]
    sibling = after(tmp_path / "sibling", state_sibling)
    assert failed(sibling) == ["outside-untouched"] and ".file-organizer/state.json.bak is new" in sibling["message"]


def test_r2_01_tools_refuse_a_state_path_that_is_not_a_file(tmp_path: Path) -> None:
    unpack(base_folder(), tmp_path)
    (tmp_path / ".file-organizer/state.json").mkdir(parents=True)
    for tool in (organizer.pin_layout, organizer.survey):
        organizer.RUN = None
        with pytest.raises(ValueError, match=r"\.file-organizer/state\.json is not a regular file"):
            tool(OrganizeInput(folder=FOLDER), tmp_path)


def test_fo02_hidden_and_outside_hold_for_the_whole_agent_folder(tmp_path: Path) -> None:
    files = {path.removeprefix("Downloads/"): data for path, data in base_folder().items()}
    files[".file-organizer/notes.txt"] = b"a member's own file in the plugin's folder\n"
    verdict = after(tmp_path, lambda workspace, _output: None, files, ".")
    assert verdict["valid"], verdict["message"]
    tampered = after(tmp_path / "again", lambda workspace, _output: (workspace / ".file-organizer/notes.txt").write_text("changed"), files, ".")
    assert failed(tampered) == ["hidden-untouched"]


# ----- FO-03: unreadable files and folders -----


def test_fo03_an_unreadable_file_or_folder_is_refused_plainly(tmp_path: Path) -> None:
    unpack({**base_folder(), "Downloads/locked.txt": b"secret\n", "Documents/locked/x.txt": b"x\n"}, tmp_path)
    (tmp_path / "Downloads/locked.txt").chmod(0)
    (tmp_path / "Documents/locked").chmod(0)
    try:
        for tool in (organizer.pin_layout, organizer.survey):
            organizer.RUN = None
            with pytest.raises(ValueError, match="cannot organize Downloads") as refused:
                tool(OrganizeInput(folder=FOLDER), tmp_path)
            assert "Downloads/locked.txt cannot be read" in str(refused.value) and "Documents/locked cannot be read" in str(refused.value)
    finally:
        (tmp_path / "Downloads/locked.txt").chmod(0o644)
        (tmp_path / "Documents/locked").chmod(0o755)


@pytest.mark.parametrize("what", ["target", "folder"])
def test_fo03_the_verdict_never_raises_on_unreadable_entries(tmp_path: Path, what: str) -> None:
    workspace, reference, output = host_run(tmp_path, base_folder(), FOLDER)
    locked = next((workspace / "Downloads/organized/documents/pdf").rglob("*.pdf")) if what == "target" else workspace / "Downloads/locked"
    if what == "folder":
        locked.mkdir()
        (locked / "x.txt").write_text("x")
    locked.chmod(0)
    try:
        verdict = judge(workspace, reference, output, FOLDER)
    finally:
        locked.chmod(0o755)
    assert not verdict["valid"] and verdict["score"] == 0.0
    assert "cannot be read" in verdict["message"] and failed(verdict) == ["plain-entries"]


# ----- FO-04: symlinks -----


@pytest.mark.parametrize("link", ["file", "folder"])
def test_fo04_a_symlink_is_refused_and_the_verdict_says_so(tmp_path: Path, link: str) -> None:
    workspace, scratch = tmp_path / "workspace", tmp_path / "scratch"
    unpack({"Downloads/a.txt": b"a\n", "Downloads/target.txt": b"t\n", "Other/p1.txt": b"p1\n"}, workspace)
    if link == "file":
        (workspace / "Downloads/link.txt").symlink_to("target.txt")
    else:
        (workspace / "Downloads/linkdir").symlink_to("../Other")
    shutil.copytree(workspace, scratch)  # as NanoAgent stages the reference: the link is followed
    reference = organizer.pin_layout(OrganizeInput(folder=FOLDER), scratch)
    name = "Downloads/link.txt" if link == "file" else "Downloads/linkdir"
    with pytest.raises(ValueError, match=f"{name} is a symlink"):
        organizer.survey(OrganizeInput(folder=FOLDER), workspace)
    nothing = OrganizeOutput(folder=FOLDER, files=0, moved=0, deleted=0, stayed=0, left=0, remaining=0)
    verdict = judge(workspace, reference, nothing, FOLDER)
    assert not verdict["valid"] and verdict["score"] == 0.0
    assert verdict["message"].startswith("plain-entries: The rules refuse your File Organizer agent folder as it is") and f"{name} is a symlink" in verdict["message"]
    assert failed(verdict) == ["plain-entries"]  # nothing blames the agent


def test_fo04_a_symlink_in_a_hidden_folder_is_refused_too(tmp_path: Path) -> None:
    unpack({"Downloads/a.txt": b"a\n", "Downloads/.git/HEAD": b"ref\n"}, tmp_path)
    (tmp_path / "Downloads/.git/link").symlink_to("HEAD")
    assert "Downloads/.git/link is a symlink" in look(tmp_path, FOLDER).refused


# ----- FO-05: folders count -----


def empty_left(workspace, _output):
    (workspace / "Downloads/organized/images/empty-left").mkdir()
    (workspace / "Downloads/old/deeper").mkdir()


def junk_replaced_by_folder(workspace, _output):
    (workspace / "Downloads/photos/Thumbs.db/cache").mkdir(parents=True)


@pytest.mark.parametrize("tamper", [empty_left, junk_replaced_by_folder])
def test_fo05_no_empty_folder_may_remain(tmp_path: Path, tamper) -> None:
    verdict = after(tmp_path, tamper)
    assert failed(verdict) == ["nothing-extra"] and "(an empty folder)" in verdict["message"]


def test_fo05_a_run_starts_by_removing_empty_folders(tmp_path: Path) -> None:
    files = {"Done/organized/documents/txt/undated/undated_a.txt": b"a\n"}
    workspace, scratch = tmp_path / "workspace", tmp_path / "scratch"
    unpack(files, workspace)
    for empty in ("Done/organized/documents/txt/undated/undated_b.txt", "Done/old/deeper", "Done/organized/images"):
        (workspace / empty).mkdir(parents=True)
    shutil.copytree(workspace, scratch)
    reference = organizer.pin_layout(OrganizeInput(folder="Done"), scratch)
    assert reference.taken == ["organized", "organized/documents", "organized/documents/txt", "organized/documents/txt/undated", "organized/documents/txt/undated/undated_a.txt"]
    survey = organizer.survey(OrganizeInput(folder="Done"), workspace)  # an idle run: nothing to do but this
    assert not survey.rows
    assert not (workspace / "Done/old").exists() and not (workspace / "Done/organized/images").exists()
    verdict = judge(workspace, reference, survey.summary, "Done")
    assert verdict["valid"], verdict["message"]
    assert reference.entries_after == count_below(workspace)


# ----- FO-06 and FO-07: linear text scans; JSON depth is a rule -----


def test_fo06_front_matter_is_read_in_linear_time() -> None:
    data = b"---\ndate:" + b" " * 400_000 + b"x\n---\n# Title\n"
    started = time.perf_counter()
    fact = describe("notes.md", data)
    assert time.perf_counter() - started < 1.0
    assert fact.type == "md" and fact.date is None
    assert describe("a.md", b"---\ndate: \t'2020-01-02' \t\r\n---\n").date == "2020-01-02"
    late = b"---\n" + b"x: y\n" * 1000 + b"date: 2020-01-02\n"
    assert describe("late.md", late).date is None  # front matter is read from the first 1,000 lines


def nested(depth: int) -> str:
    return "[" * depth + "]" * depth


def deep_call(levels: int, check):
    return check() if levels == 0 else deep_call(levels - 1, check)


def test_fo07_json_depth_is_a_rule_not_the_stack() -> None:
    assert is_json(nested(512)) and not is_json(nested(513))
    assert deep_call(800, lambda: is_json(nested(512)))  # however deep the caller's stack
    assert not is_json(nested(10_000))
    assert is_json('["]]]]", [[{"a": "\\\\"}]]]')
    assert describe("deep", nested(513).encode()).type == "txt"
    assert describe("deep", nested(512).encode()).type == "json"
    assert sys.getrecursionlimit() == 1000


# ----- FO-08 to FO-12: types -----


def test_fo08_utf16_and_utf32_text_is_text_before_mpeg() -> None:
    note = "Notes from Tuesday\r\nbuy milk\r\n"
    assert kind("Notes from Tuesday.txt", b"\xff\xfe" + note.encode("utf-16-le")) == "documents/txt/txt"
    assert kind("backup.reg", b"\xff\xfe" + "Windows Registry Editor Version 5.00\r\n".encode("utf-16-le")) == "other/reg/reg"
    assert kind("be.txt", b"\xfe\xff" + note.encode("utf-16-be")) == "documents/txt/txt"
    assert kind("wide.csv", b"\xff\xfe\x00\x00" + "a,b\n1,2\n3,4\n".encode("utf-32-le")) == "spreadsheets/csv/csv"
    assert kind("x", b"\xff\xfe" + "# Title\n".encode("utf-16-le")) == "documents/md/md"


def test_fo08_mpeg_needs_a_valid_header_and_a_second_frame() -> None:
    assert kind("song.mp3", builders.mp3(2, None)) == "audio/mp3/mp3"  # two frames, no ID3
    assert kind("song", builders.mp3(2, None)[:300]) == "audio/mp3/mp3"  # shorter than one frame: one header is enough
    lone = b"\xff\xfb\x90\x64" + bytes(range(256)) * 3
    assert kind("noise.dat", lone) == "other/dat/dat"  # a header, then no second frame
    assert kind("free.mp3", b"\xff\xfb\x00\x64" + b"\x00" * 900) == "other/bin/bin"  # free-format bitrate: not a header


def test_fo09_windows_1252_text_with_a_text_extension_is_text() -> None:
    table = "Name,Ciudad,Año\nJosé,Bogotá,1999\nRenée,Zürich,2001\n".encode("cp1252")
    assert kind("people.csv", table) == "spreadsheets/csv/csv"
    assert kind("page.html", "<html><body>Café “crème”</body></html>".encode("cp1252")) == "documents/html/html"
    assert kind("people", table) == "other/bin/bin"  # no claimed text extension: not text
    assert kind("odd.txt", b"caf\xe9 \x81") == "other/bin/bin"  # 0x81 is undefined in Windows-1252
    assert kind("ctl.txt", b"caf\xe9 \x01") == "other/bin/bin"  # a control character
    assert describe("old.md", "---\ndate: 2011-03-04\n---\n# Café\n".encode("cp1252")).date == "2011-03-04"


def test_fo10_text_keeps_an_unlisted_extension() -> None:
    gpx = b'<?xml version="1.0"?><gpx version="1.1"><trk/></gpx>\n'
    assert kind("Geotag.gpx", gpx) == "other/gpx/gpx"
    assert kind("Geotag.kml", b'<?xml version="1.0"?><kml/>\n') == "other/kml/kml"
    assert kind("Info.plist", b'<?xml version="1.0"?><plist/>\n') == "other/plist/plist"
    assert kind("Makefile", b"all:\n\tcc main.c\n") == "documents/txt/txt"
    assert kind("Dockerfile", b"FROM python:3.12\n") == "documents/txt/txt"
    assert describe("Geotag.gpx", gpx).base != describe("Geotag.kml", b"<kml/>").base




def test_fo11_office_files_keep_their_own_extension() -> None:
    xlsm = builders.office_zip("xl/workbook.xml", "application/vnd.ms-excel.sheet.macroEnabled.main+xml")
    assert kind("issue221.xlsm", xlsm) == "spreadsheets/xlsm/xlsm" == kind("renamed.xlsx", xlsm)
    assert describe("issue221.xlsm", xlsm).date == "2021-05-06"
    assert kind("a.docm", builders.office_zip("word/document.xml", "application/vnd.ms-word.document.macroEnabled.main+xml")) == "documents/docm/docm"
    assert kind("a", builders.office_zip("word/document.xml", "application/vnd.ms-word.template.macroEnabledTemplate.main+xml")) == "documents/dotm/dotm"
    assert kind("a.pptx", builders.office_zip("ppt/presentation.xml", "application/vnd.openxmlformats-officedocument.presentationml.slideshow.main+xml")) == "presentations/ppsx/ppsx"
    assert kind("a.xlsb", builders.office_zip("xl/workbook.bin", None, "application/vnd.ms-excel.sheet.binary.macroEnabled.main")) == "spreadsheets/xlsb/xlsb"
    bare = builders.office_zip("xl/workbook.xml", None)
    assert kind("t.xltm", bare) == "spreadsheets/xltm/xltm"  # no content type: a claimed extension of the family
    assert kind("t.docm", bare) == "spreadsheets/xlsx/xlsx"  # another family's extension: the plain one
    assert kind("t.docm", b"\x00\x01 not a zip") == "other/bin/bin"  # Office extensions are the table's: never kept
    assert kind("t.docm", b"just text, not a zip\n") == "documents/txt/txt"  # text claiming one: its content decides


def test_fo12_classic_quicktime_and_transport_streams() -> None:
    mvhd = builders.full_box(b"mvhd", 0, 0, struct.pack(">IIII", 3_500_000_000, 3_500_000_000, 600, 600) + b"\x00" * 80)
    classic = builders.box(b"moov", mvhd) + builders.box(b"mdat", b"\x00" * 32)
    assert kind("QuickTime.mov", classic) == "video/mov/mov" == kind("clip", classic)
    assert describe("QuickTime.mov", classic).date == "2014-11-28"  # 3,500,000,000 s after 1904-01-01: 2014-11-28 06:13:20
    wide = builders.box(b"wide", b"") + builders.box(b"mdat", b"\x01" * 40) + builders.box(b"moov", mvhd)
    assert kind("old.mov", wide) == "video/mov/mov"
    packets = b"".join(b"\x47" + bytes([index % 256]) * 187 for index in range(5))
    assert kind("broadcast.ts", packets) == "video/ts/ts" == kind("broadcast", packets)
    assert kind("short.ts", packets[: 188 * 2]) == "other/bin/bin"


# ----- FO-13 and FO-16: dates, malformed structures -----


def test_fo13_the_pdf_information_dictionary_decides() -> None:
    latex = (
        b"%PDF-1.5\n3 0 obj << /Producer (pdfTeX) /CreationDate (D:20170131010939Z) >> endobj\n"
        b"9 0 obj << /Type /XObject /CreationDate (D:20141219120000) >> endobj\n"  # an embedded figure's own date
        b"trailer << /Root 1 0 R /Info 3 0 R >>\n%%EOF\n"
    )
    assert describe("arxiv-1412.6980v9.pdf", latex).date == "2017-01-31"
    packed = b"%PDF-1.5\n9 0 obj << /CreationDate (D:20141219120000) >> endobj\ntrailer << /Info 3 0 R >>\n%%EOF\n"
    assert describe("packed.pdf", packed).date == "2014-12-19"  # the Info object is compressed: the last literal
    bare = b"%PDF-1.5\n3 0 obj << /Producer (x) >> endobj\n9 0 obj << /CreationDate (D:20141219) >> endobj\ntrailer << /Info 3 0 R >>\n"
    assert describe("bare.pdf", bare).date is None
    assert describe("bare 2018-02-03.pdf", bare).date == "2018-02-03"






def test_fo13_cr3_dates_come_from_its_cmt_boxes() -> None:
    original = b"2021:05:12 10:11:12\x00"
    with_cmt2 = builders.cr3(builders.tiff_ifd([(0x010F, 2, b"Canon\x00")]), builders.tiff_ifd([(0x9003, 2, original)]))
    assert kind("IMG_0001.CR3", with_cmt2) == "images/raw/cr3" and describe("IMG_0001.CR3", with_cmt2).date == "2021-05-12"
    exif_ifd_at = 8 + 2 + 12 + 4  # CMT1's IFD0 points to an Exif IFD right after it
    exif = struct.pack("<H", 1) + struct.pack("<HHII", 0x9003, 2, 20, exif_ifd_at + 2 + 12 + 4) + b"\x00" * 4 + b"2018:02:21 09:00:00\x00"
    cmt1 = b"II*\x00" + struct.pack("<I", 8) + struct.pack("<H", 1) + struct.pack("<HHII", 0x8769, 4, 1, exif_ifd_at) + b"\x00" * 4 + exif
    assert describe("CanonRaw.cr3", builders.cr3(cmt1, builders.tiff_ifd([(0x010F, 2, b"Canon\x00")]))).date == "2018-02-21"
    assert describe("none.cr3", builders.cr3(builders.tiff_ifd([(0x010F, 2, b"Canon\x00")]), None)).date is None


def test_fo16_malformed_structures_give_no_date() -> None:
    photo = builders.jpeg(1, "2019-07-14")
    app1 = photo.index(b"\xff\xe1")
    assert describe("cut.jpg", photo[: app1 + 30]).date is None  # the Exif segment runs past the end
    document = builders.office_zip("word/document.xml", None)
    end = document.rindex(b"PK\x05\x06")
    for comment in (b"PK\x05\x06" + b"\x00" * 14, b"PK\x05\x06" + b"\x00" * 16 + struct.pack("<H", 7)):  # a stray end record in the comment
        commented = document[: end + 20] + struct.pack("<H", len(comment)) + comment
        assert kind("letter.docx", commented) == "documents/docx/docx"
    # a stray record that does reach the end of the file is the one read: its directory starts where it says
    forged_at = end + 22
    forged = document[: end + 20] + struct.pack("<H", 22) + b"PK\x05\x06" + b"\x00" * 12 + struct.pack("<IH", forged_at, 0)
    assert kind("letter.docx", forged) == "archives/zip/zip"  # its directory (from itself to itself) holds no names
    pointing_back = document[: end + 20] + struct.pack("<H", 22) + b"PK\x05\x06" + b"\x00" * 12 + struct.pack("<IH", 0, 0)
    assert kind("letter.docx", pointing_back) == "documents/docx/docx"  # from the file's start: the real headers are in it
    assert kind("letter.docx", document + b"trailing bytes") == "archives/zip/zip"  # no end record reaches the end: no names


# ----- FO-14: the decisions RULES.md now makes -----


def test_fo14_decisions_written_in_rules() -> None:
    assert kind("x", b"\xef\xbb\xbf# Title\n") == "documents/md/md"  # (1) the BOM is not part of `first`
    assert kind("x", b'\xef\xbb\xbf{"a": 1}') == "data/json/json"  # (2) JSON is read without its BOM
    assert kind("x", b"[NaN, Infinity]") == "documents/txt/txt"  # (3) NaN and Infinity are not JSON
    assert describe("2019-02-30 then 2019-03-01.txt", b"x\n").date == "2019-03-01"  # (4) the first real date
    assert describe("2019-02-30 then 2019-03-01.txt", b"x\n").slug == "2019-02-30-then"  # (5) a skipped candidate stays
    assert describe("a.md", b"---\ndate: 2020-01-02\n").date == "2020-01-02"  # (6) no closing line needed
    assert describe("b.md", b"---\ntitle: x\n \t---\t\ndate: 2020-01-02\n").date is None  # (6) a closing line may hold spaces and tabs
    assert kind("a.jpeg", builders.plain_zip(1, None)) == "archives/zip/zip"  # (7) aliases are never kept
    assert kind("a.bin", builders.plain_zip(1, None)) == "other/bin/bin"  # a claimed bin is kept as bin
    empty_in_place = describe("organized/documents/txt/undated/undated_a.txt", b"")
    assert not empty_in_place.conforming and empty_in_place.base is None  # (8) empty files never conform
    assert kind("a.orf", b"IIRO\x08\x00\x00\x00") == "other/orf/orf"  # (9) a raw that is not TIFF-shaped
    assert kind("a.cr3", b"\x00not a canon raw") == "other/bin/bin"  # (9) cr3 is the table's
    png = builders.png(1, "2014-03-07")
    assert describe("p.png", png).date == "2014-03-07"  # (10) eXIf with or without `Exif\0\0`
    for text in ("Fri, 7 Mar 2014 10:00:00", "07 Mar 2014", " 7\tmar   2014"):  # (11) day forms and spaces
        assert describe("t.png", builders.png_with_text(text)).date == "2014-03-07", text





def test_fo14_the_path_limit_counts_from_the_agent_folder(tmp_path: Path) -> None:
    inner = "a" * 100 + "/" + "b" * 100 + "/"
    name = "x" * (300 - len("Downloads/" + inner) - 4) + ".txt"
    unpack({f"Downloads/{inner}{name}": b"x\n"}, tmp_path)
    assert look(tmp_path, FOLDER).refused is None
    longer = "y" * (301 - len("Downloads/" + inner) - 4) + ".txt"
    unpack({f"Downloads/{inner}{longer}": b"y\n"}, tmp_path)
    assert f"Downloads/{inner}{longer} is longer than 300 characters" in look(tmp_path, FOLDER).refused


# ----- FO-15: entries after the run -----


@pytest.mark.parametrize("layout", ["whole-with-state-files", "hidden-in-subfolders", "nested-folder"])
def test_fo15_entries_after_is_what_the_run_leaves(tmp_path: Path, layout: str) -> None:
    files = base_folder()
    folder = FOLDER
    if layout == "whole-with-state-files":
        files = {path.removeprefix("Downloads/"): data for path, data in files.items()}
        files[".file-organizer/notes.txt"] = b"mine\n"
        folder = "."
    elif layout == "hidden-in-subfolders":
        files["Downloads/deep/er/.hidden"] = b"h\n"
        files["Downloads/deep/er/moved.txt"] = b"moved\n"
    else:
        files = {("Photos/2019/" + path.removeprefix("Downloads/") if path.startswith("Downloads/") else path): data for path, data in files.items()}
        folder = "Photos/2019"
    workspace, reference, output = host_run(tmp_path, files, folder)
    assert judge(workspace, reference, output, folder)["valid"]
    assert reference.entries_after == count_below(workspace)


def test_fo15_the_folder_is_named_as_listed(tmp_path: Path) -> None:
    unpack({"Downloads/a.txt": b"a\n"}, tmp_path)
    found = look(tmp_path, "downloads")
    assert found.refused.startswith("No folder downloads in your File Organizer agent folder; it holds Downloads/")


# ----- FO-17: the copy kept -----


def keeper(files: dict[str, bytes], tmp_path: Path) -> str:
    unpack(files, tmp_path)
    steps = look(tmp_path, FOLDER).steps
    kept = {step.path for step in steps if step.action != "delete"}
    return next(iter(kept & {path.removeprefix("Downloads/") for path in files}))


@pytest.mark.parametrize(
    ("names", "kept"),
    [
        (["Inbox/logo", "Inkscape-small.svg"], "Inkscape-small.svg"),  # names its type, shallower
        (["Selfie (1).jpg", "Selfie of iPhone in Mirror.jpg"], "Selfie of iPhone in Mirror.jpg"),  # no copy marker
        (["a/b/report.pdf", "c/report.pdf"], "c/report.pdf"),  # shallowest
        (["Copy of plan.txt", "plan - Copy.txt", "plan.txt"], "plan.txt"),
        (["z.txt", "a.txt"], "a.txt"),  # then code-point order
    ],
)
def test_fo17_the_copy_kept_has_the_most_original_name(tmp_path: Path, names: list[str], kept: str) -> None:
    data = b'<svg xmlns="http://www.w3.org/2000/svg"/>\n' if kept.endswith(".svg") else (CANON if kept.endswith(".jpg") else b"same bytes\n")
    if kept.endswith(".pdf"):
        data = builders.pdf(3, "2019-01-02")
    assert keeper({f"Downloads/{name}": data for name in names}, tmp_path) == kept


def test_fo17_order_is_conforming_then_marker_then_type_then_depth() -> None:
    facts = [describe(path, b"same\n") for path in ("b/x (2).txt", "a/x", "x.txt", "organized/documents/txt/undated/undated_x.txt")]
    assert [fact.path for fact in ordered(facts)] == ["organized/documents/txt/undated/undated_x.txt", "x.txt", "a/x", "b/x (2).txt"]


def test_fo13_cr3_falls_back_to_cmt1_when_cmt2_gives_no_real_date() -> None:
    exif_ifd_at = 8 + 2 + 12 + 4
    exif = struct.pack("<H", 1) + struct.pack("<HHII", 0x9003, 2, 20, exif_ifd_at + 2 + 12 + 4) + b"\x00" * 4 + b"2018:02:21 09:00:00\x00"
    cmt1 = b"II*\x00" + struct.pack("<I", 8) + struct.pack("<H", 1) + struct.pack("<HHII", 0x8769, 4, 1, exif_ifd_at) + b"\x00" * 4 + exif
    blank = builders.tiff_ifd([(0x9003, 2, b"    :  :     :  :  \x00")])
    data = builders.cr3(cmt1, blank)
    assert describe("blank.cr3", data).date == "2018-02-21"
    assert oracle_facts("blank.cr3", data)["date"] == "2018-02-21"


# ----- R2-02: every reader stops at a written limit, so the verifier's work is bounded -----


@pytest.mark.parametrize(
    ("name", "found"),
    [
        ("within reach.docx", "documents/docm/docm 2016-05-04"),
        ("past reach.docx", "documents/docm/docm None"),  # the date lies past the part's first 4,096 bytes
        ("fifth block.docx", "documents/docm/docm None"),  # or in its fifth DEFLATE block
        ("stored past reach.docx", "documents/docm/docm None"),
        ("late override.docx", "documents/docx/docx 2016-05-04"),  # the content type lies past the reach: the plain docx
        ("16 strays.docx", "documents/docm/docm 2016-05-04"),
        ("17 strays.docx", "archives/zip/zip None"),  # the end record is the 17th PK 5 6 from the end: not tried
        ("markers within.jpg", "images/jpg/jpg 2012-03-04"),
        ("markers past.jpg", "images/jpg/jpg None"),
        ("chunks within.png", "images/png/png 2015-06-07"),
        ("chunks past.png", "images/png/png None"),
        ("text within.png", "images/png/png 2015-06-07"),
        ("text past.png", "images/png/png None"),
        ("chunks within.webp", "images/webp/webp 2013-04-05"),
        ("chunks past.webp", "images/webp/webp None"),
        ("boxes within.mp4", "video/mp4/mp4 2014-11-28"),
        ("boxes past.mp4", "video/mp4/mp4 None"),
        ("csv 1000 lines", "documents/txt/txt None"),
        ("csv 1001 lines", "spreadsheets/csv/csv None"),  # line 1,001 is past the CSV test's reach
    ],
)
def test_r2_02_readers_stop_at_their_written_limits(name: str, found: str) -> None:
    fact = describe(name, builders.limit_files()[name])
    assert f"{fact.group}/{fact.type}/{fact.ext} {fact.date}" == found


def test_r2_02_the_costliest_files_describe_in_bounded_time() -> None:
    """The review's perf_probe files, each at most ~10 MiB: none takes more than a few milliseconds per MiB."""
    import random as rng_module

    from perf import worst

    rng = rng_module.Random(2)
    for build in (*[build for _ext, build in worst.KINDS], lambda rng, size: worst.dense_docx(rng, 8192, 1500)):
        data = build(rng, 10 * 1024 * 1024 - 4096)
        started = time.perf_counter()
        describe("probe", data)
        assert time.perf_counter() - started < 0.4, build
    dense = worst.challenger_dense(1)
    started = time.perf_counter()
    describe("dense-meta.docx", next(iter(dense.values())))  # 1.5 s before the limits; now the first 4,096 bytes
    assert time.perf_counter() - started < 0.05


# ----- R3-01: a state.json the plugin did not write is refused, not overwritten -----


@pytest.mark.parametrize(
    "content",
    [
        b"my own notes, which happen to live here\n",  # a member's own file
        b'{"version": 1, "token": "0", "folder": "Downloads", "hash_length": 12, "taken": [], "rows": [',  # a truncated state
        b'{"version": 1, "folder": "Downloads"}',  # JSON, but not the run state
        b"[" * 600 + b"]" * 600,  # nested past 512
    ],
)
def test_r3_01_a_state_json_that_is_not_the_run_state_is_refused(tmp_path: Path, content: bytes) -> None:
    unpack({**base_folder(), ".file-organizer/state.json": content}, tmp_path)
    for tool in (organizer.pin_layout, organizer.survey):
        organizer.RUN = None
        with pytest.raises(ValueError, match="state.json is not this plugin's run state: rename or remove it, then ask again"):
            tool(OrganizeInput(folder=FOLDER), tmp_path)
    assert (tmp_path / ".file-organizer/state.json").read_bytes() == content  # left as it was


def test_r3_01_an_earlier_runs_state_is_the_plugins_to_rewrite(tmp_path: Path) -> None:
    workspace, _reference, _output = host_run(tmp_path, base_folder(), FOLDER)
    earlier = (workspace / ".file-organizer/state.json").read_bytes()
    organizer.RUN = None
    organizer.survey(OrganizeInput(folder=FOLDER), workspace)  # the next run starts from the earlier run's state
    assert (workspace / ".file-organizer/state.json").read_bytes() != earlier
