"""Writes the scripted cases (tests/cases/*.json) and the agent folders they unpack
(tests/cases/folders/*.tar.gz), deterministically:

    uv run python tests/cases/build_cases.py

Every case runs the organize-folder task through NanoAgent's real task runner with a scripted agent
(~/mochi-dev/harness/scripted_task.py, or tests/test_cases.py without NanoAgent): survey, a python step
that decides the rows by the instructions (tests/cases/agent.py, inlined), apply in calls of 30, submit.
Gold cases must be valid with score 1.0; each wrong case makes one mistake and must be invalid with the
message of the first constraint it breaks. The review's red-team tampering (hidden entries, files outside
the folder, empty folders, symlinks, unreadable and special files) is replayed by the wrong_* cases whose
python step runs after the applies.
"""

from __future__ import annotations

import gzip
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(ROOT / "tests")]

from flow import agent, organize_fully, plain_rows, tree
from messy import messy, organized_folder, unpack, write_tar

from contract import OrganizeInput
from plugin import organizer

AGENT = (HERE / "agent.py").read_text(encoding="utf-8")
FOLDERS = HERE / "folders"


def rows_for(files: dict[str, bytes], folder: str) -> list[dict]:
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        unpack(files, workspace)
        organizer.RUN = None
        survey = organizer.survey(OrganizeInput(folder=folder), workspace)
        organizer.RUN = None
        return plain_rows(survey), survey.summary


def suits(rows: list[dict]) -> bool:
    """A folder every wrong case can be made on: duplicates among the rows, a collision, junk."""
    decided = agent().plan_rows(rows)
    bases = [row["base"] for row, action, _n in decided if action == "move"]
    copies = sum(1 for row, action, _n in decided if action == "delete" and not row["drop"])
    try:
        agent().keeper_wrong(decided)
    except RuntimeError:
        return False
    return copies >= 1 and len(bases) != len(set(bases)) and any(row["drop"] in ("junk", "empty") for row in rows)


def pick(profile: str, folder: str, one_run: bool) -> tuple[int, dict[str, bytes]]:
    for seed in range(1, 400):
        files = messy(seed, profile, folder)
        rows, summary = rows_for(files, folder)
        if suits(rows) and (summary.remaining == 0) == one_run:
            return seed, files
    raise SystemExit(f"no seed suits {profile}")


def save_folder(name: str, files: dict[str, bytes], links: dict[str, str] | None = None, empty: tuple[str, ...] = ()) -> str:
    plain = FOLDERS / f"{name}.tar"
    write_tar(files, plain, links, empty)
    packed = FOLDERS / f"{name}.tar.gz"
    with gzip.GzipFile(packed, "wb", mtime=0, compresslevel=9) as out:
        out.write(plain.read_bytes())
    plain.unlink()
    return f"folders/{name}.tar.gz"


def root_code(folder: str) -> str:
    return "workspace" if folder == "." else f"workspace / {folder!r}"


def steps(folder: str, mistake: str | None = None, after: str | None = None, submit: str | dict = "$ref:last.summary") -> list[dict]:
    flow = [
        {"tool": "survey", "arguments": {"folder": folder}, "save_as": "survey"},
        {"python": AGENT + f"\ndecide(outputs, {folder!r}, {mistake!r})\n"},
        {"tool": "apply", "arguments": "$ref:batch0", "save_as": "last"},
        {"tool": "apply", "arguments": "$ref:batch1", "save_as": "last"},
    ]
    if mistake == "fix_errors":
        flow.append({"tool": "apply", "arguments": "$ref:fix", "save_as": "last"})
    if after:
        flow.append({"python": after})
    flow.append({"tool": "submit", "arguments": submit})
    return flow


def moved_file(folder: str, body: str) -> str:
    """Python run after the applies, with `target` and `source` bound to one applied move's paths."""
    return (
        "state = json.loads((workspace / '.file-organizer' / 'state.json').read_text())\n"
        "move = next(entry for entry in state['applied'] if entry['kind'] == 'move')\n"
        f"root = {root_code(folder)}\n"
        "target, source = root / move['to'], root / move['from']\n" + body
    )


# Python run after the applies, with `root`, `rows` (the run's rows by i), `moved` (sha256 -> where the run
# moved those bytes) and `duplicate` (a duplicate the run deleted: its old name and its bytes) bound.
RUN_FACTS = (
    "import os\n"
    "state = json.loads((workspace / '.file-organizer' / 'state.json').read_text())\n"
    "rows = {row['i']: row for row in state['rows']}\n"
    "moved = {rows[entry['i']]['sha256']: entry['to'] for entry in state['applied'] if entry['kind'] == 'move'}\n"
    "root = workspace / 'Downloads'\n"
    "gone = next(entry for entry in state['applied'] if entry['kind'] == 'delete' and rows[entry['i']]['sha256'] in moved)\n"
    "duplicate = (gone['path'].rpartition('/')[2], (root / moved[rows[gone['i']]['sha256']]).read_bytes())\n"
)
TAMPERS = {
    "hidden_deleted": ("a hidden file the rules leave alone is deleted", "(root / '.git' / 'HEAD').unlink()\n", "hidden entry"),
    "hidden_modified": ("a hidden file the rules leave alone is changed", "(root / '.vscode' / 'settings.json').write_text('{\"tampered\": true}')\n", "hidden entry"),
    "hidden_stray_copy": ("a copy of a moved file is left under a hidden name", "(root / '.backup-copy').write_bytes(duplicate[1])\n", "hidden entry"),
    "duplicate_hidden": ("a duplicate the rules delete ends up under a hidden name instead", "(root / ('.' + duplicate[0])).write_bytes(duplicate[1])\n", "hidden entry"),
    "duplicate_into_hidden_folder": ("a duplicate the rules delete ends up in a hidden folder instead", "(root / '.trash').mkdir()\n(root / '.trash' / duplicate[0]).write_bytes(duplicate[1])\n", "hidden entr"),
    "junk_hidden": ("junk the rules delete ends up under a hidden name instead", "(root / '.Thumbs-kept.db').write_bytes(b'junk')\n", "hidden entry"),
    "outside_deleted": ("a file outside the folder is deleted", "(workspace / 'Notes' / 'keep me.txt').unlink()\n", "outside Downloads"),
    "outside_modified": ("a file outside the folder is overwritten", "(workspace / 'Notes' / 'keep me.txt').write_text('wiped')\n", "outside Downloads"),
    "duplicate_moved_outside": ("a duplicate the rules delete is moved out of the folder instead", "(workspace / 'Elsewhere').mkdir()\n(workspace / 'Elsewhere' / duplicate[0]).write_bytes(duplicate[1])\n", "outside Downloads"),
    "empty_folder_left": ("empty folders are left in the folder", "(root / 'organized' / 'empty-left').mkdir()\n(root / 'old' / 'deeper').mkdir(parents=True)\n", "(an empty folder)"),
    "junk_replaced_by_folder": ("junk is left as a folder of the same name", "(root / 'Thumbs.db' / 'cache').mkdir(parents=True)\n", "(an empty folder)"),
    "fifo_added": ("a FIFO appears in the folder", "os.mkfifo(root / 'pipe')\n", "Downloads/pipe is not a regular file or folder"),
    "unreadable_target": ("a moved file cannot be read at its target", "(root / next(iter(moved.values()))).chmod(0)\n", "cannot be read"),
    "state_stash_file": (
        "a duplicate the rules delete is kept under the run state's name (the review's rt_state_stash_file2)",
        (
            "os.replace(workspace / '.file-organizer' / 'state.json', workspace / '.file-organizer' / 'old.json')\n"
            "(workspace / '.file-organizer' / 'state.json').write_bytes(duplicate[1])\n"
            "(workspace / '.file-organizer' / 'old.json').unlink()\n"
        ),
        ".file-organizer/state.json is not the run state the plugin writes",
    ),
    "state_stash_folder": (
        "the run state is replaced by a folder holding a duplicate, a symlink and a FIFO (the review's rt_state_stash_folder2)",
        (
            "state = workspace / '.file-organizer' / 'state.json'\n"
            "state.unlink()\n"
            "(state / 'stash').mkdir(parents=True)\n"
            "(state / 'stash' / duplicate[0]).write_bytes(duplicate[1])\n"
            "os.symlink('/etc', state / 'stash' / 'etc-link')\n"
            "os.mkfifo(state / 'pipe')\n"
        ),
        ".file-organizer/state.json is not a regular file",
    ),
}


def case(note: str, folder: str, agent_folder: str, flow: list[dict], expect: dict, **extra) -> dict:
    return {"note": note, "task": "organize-folder", "arguments": {"folder": folder}, "agent_folder": agent_folder, **extra, "steps": flow, "answer": "Done.", "expect": expect}


GOLD = {"valid": True, "score_min": 1.0}


def wrong(contains: str) -> dict:
    return {"valid": False, "score_max": 0.99, "message_contains": contains}


def main() -> int:
    FOLDERS.mkdir(exist_ok=True)
    for old in list(HERE.glob("*.json")) + list(FOLDERS.glob("*.tar.gz")):
        old.unlink()
    cases: dict[str, dict] = {}

    seed, small = pick("small", "Downloads", one_run=True)
    small_tar = save_folder("small", small)
    cases["gold_small"] = case(f"messy(seed={seed}, small): one run does everything", "Downloads", small_tar, steps("Downloads"), GOLD)
    cases["gold_scrambled_mtimes"] = case("the same folder with random modification times: the rules never read them", "Downloads", small_tar, steps("Downloads"), GOLD, mtimes="scrambled")
    hidden_check = (
        "root = workspace / 'Downloads'\n"
        "assert (root / '.git' / 'HEAD').read_bytes() == b'ref: refs/heads/main\\n'\n"
        "assert (root / '.vscode' / 'settings.json').read_bytes() == b'{\"editor.tabSize\": 2}\\n'\n"
        "assert (root / '.hidden-note.txt').read_bytes() == b'leave me alone\\n'\n"
        "assert (workspace / 'Notes' / 'keep me.txt').is_file()\n"
    )
    cases["gold_hidden_untouched"] = case("hidden files and files outside the folder are left exactly as they were", "Downloads", small_tar, steps("Downloads", after=hidden_check), GOLD)
    cases["gold_fix_errors"] = case("a junk row is first given as a move (refused), then deleted in a third call", "Downloads", small_tar, steps("Downloads", "fix_errors"), GOLD)
    stale = dict(small)
    stale[".file-organizer/state.json"] = json.dumps({"version": 1, "token": "0" * 32, "folder": "Downloads", "hash_length": 12, "taken": [], "rows": [], "applied": [{"i": 0, "kind": "delete", "path": "x", "call": 1}], "calls": 1, "summary": {}}).encode()
    cases["gold_stale_state"] = case("an earlier run's state file is in the agent folder: this run ignores and replaces it", "Downloads", save_folder("small-stale-state", stale), steps("Downloads"), GOLD)

    incremental = organized_folder(3, "Photos")
    cases["gold_incremental"] = case("an organized folder from an earlier run (files in place, a gap, a misfiled one) plus new files", "Photos", save_folder("incremental", incremental), steps("Photos"), GOLD)

    seed_multi, multi = pick("multirun", "Downloads", one_run=False)
    multi_tar = save_folder("multirun", multi)
    cases["gold_multirun_1of3"] = case(f"messy(seed={seed_multi}, multirun): this run does the first 60 actions; the rest wait", "Downloads", multi_tar, steps("Downloads"), GOLD)

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        unpack(messy(11, "small", "."), workspace)
        runs = organize_fully(workspace, ".")
        done = {path: data for path, data in tree(workspace).items() if not path.startswith(".file-organizer/")}
    cases["gold_nothing_to_do"] = case(f"a whole agent folder organized by {runs} earlier runs: nothing to do", ".", save_folder("organized-whole", done), [{"tool": "survey", "arguments": {"folder": "."}, "save_as": "survey"}, {"tool": "submit", "arguments": "$ref:survey.summary"}], GOLD)

    whole = messy(23, "small", ".")
    cases["gold_whole_agent_folder"] = case("folder . : the whole agent folder", ".", save_folder("whole", whole), steps("."), GOLD)

    cases["wrong_keeper_wrong"] = case("the last copy of duplicated bytes is kept instead of the first", "Downloads", small_tar, steps("Downloads", "keeper_wrong"), wrong("not where the rules put them"))
    cases["wrong_duplicate_kept"] = case("a duplicate copy is moved as a file of its own", "Downloads", small_tar, steps("Downloads", "duplicate_kept"), wrong("should not be"))
    cases["wrong_rank_swapped"] = case("two files sharing a base get each other's numbers", "Downloads", small_tar, steps("Downloads", "rank_swapped"), wrong("not where the rules put them"))
    cases["wrong_skipped_batch"] = case("the second call is never made", "Downloads", small_tar, steps("Downloads", "skipped_batch"), wrong("checks failed"))
    cases["wrong_junk_as_move"] = case("a junk row is given as a move (refused) and never deleted", "Downloads", small_tar, steps("Downloads", "junk_as_move"), wrong("still there"))
    fabricate = "outputs['fake'] = dict(outputs['last']['summary'], moved=outputs['last']['summary']['moved'] + 1)\n"
    cases["wrong_fabricated_summary"] = case("the submitted summary claims one more move than happened", "Downloads", small_tar, steps("Downloads", after=fabricate, submit="$ref:fake"), wrong("The submitted summary says"))
    cases["wrong_tamper_after_apply"] = case("a moved file's bytes are changed behind the tools' back", "Downloads", small_tar, steps("Downloads", after=moved_file("Downloads", "target.write_bytes(b'tampered')\n")), wrong("are gone"))
    cases["wrong_stray_file"] = case("a file the rules never made appears in the folder", "Downloads", small_tar, steps("Downloads", after="(workspace / 'Downloads' / 'stray.txt').write_text('not from the rules')\n"), wrong("should not be"))
    cases["wrong_copied_not_moved"] = case("a moved file is also copied back to where it was", "Downloads", small_tar, steps("Downloads", after=moved_file("Downloads", "source.parent.mkdir(parents=True, exist_ok=True)\nsource.write_bytes(target.read_bytes())\n")), wrong("should not be"))
    cases["wrong_out_of_quota"] = case("a number outside this run's rows is used in place of a row, which is left undone", "Downloads", multi_tar, steps("Downloads", "out_of_quota"), wrong("checks failed"))

    for name, (note, tamper, contains) in TAMPERS.items():
        cases[f"wrong_{name}"] = case(note, "Downloads", small_tar, steps("Downloads", after=RUN_FACTS + tamper), wrong(contains))
    state_rewritten = (
        "path = workspace / '.file-organizer' / 'state.json'\n"
        "state = json.loads(path.read_text())\n"
        "state['applied'], state['rows'] = [], []\n"
        "path.write_text(json.dumps(state))\n"
    )
    cases["gold_state_rewritten"] = case("the run state is rewritten after the last call: the verdict reads the folder", "Downloads", small_tar, steps("Downloads", after=state_rewritten), GOLD)

    emptied = dict(small)
    emptied["Downloads/Archive/2019/.keep"] = b""
    cases["gold_empty_folders"] = case(
        "empty folders (one nested, one named like a target) are removed when the run starts; a folder holding only a hidden file stays",
        "Downloads",
        save_folder("small-empty-folders", emptied, empty=("Downloads/empty", "Downloads/nested/deeper/deepest", "Downloads/organized/documents/txt/undated/undated_notes.txt")),
        steps("Downloads", after="assert not (workspace / 'Downloads' / 'empty').exists() and (workspace / 'Downloads' / 'Archive' / '2019' / '.keep').exists()\n"),
        GOLD,
    )
    long_line = "---\ndate:" + " " * 400_000 + "x\n---\n# Notes\n"
    texts = {
        "Downloads/notes.md": long_line.encode(),
        "Downloads/deep-512": ("[" * 512 + "]" * 512).encode(),
        "Downloads/deep-513": ("[" * 513 + "]" * 513).encode(),
        "Downloads/Notes from Tuesday.txt": b"\xff\xfe" + "Notes from Tuesday\r\n".encode("utf-16-le"),
        "Downloads/ventas.csv": "Nombre,Ciudad\nJosé,Bogotá\nRenée,Zürich\n".encode("cp1252"),
        "Downloads/Geotag.gpx": b'<?xml version="1.0"?><gpx/>\n',
        "Downloads/Geotag.kml": b'<?xml version="1.0"?><kml/>\n',
    }
    cases["gold_text_edges"] = case("a 400 KB front matter line, JSON 512 and 513 deep, UTF-16 and Windows-1252 text, unlisted text extensions", "Downloads", save_folder("text-edges", texts), steps("Downloads"), GOLD)

    links = {"Downloads/a.txt": b"a\n", "Downloads/target.txt": b"t\n", "Other/p1.txt": b"p1\n"}
    nothing = {"folder": "Downloads", "files": 0, "moved": 0, "deleted": 0, "stayed": 0, "left": 0, "remaining": 0}
    refused = [{"tool": "survey", "arguments": {"folder": "Downloads"}, "expect_error": True}, {"tool": "submit", "arguments": nothing}]
    cases["wrong_symlink_file"] = case("the folder holds a symlink: survey refuses it, and the verdict says the rules refuse the folder", "Downloads", save_folder("symlink-file", links, links={"Downloads/link.txt": "target.txt"}), refused, wrong("Downloads/link.txt is a symlink"))
    locked = [{"python": "(workspace / 'Downloads' / 'a.txt').chmod(0)\n"}, *refused]
    cases["wrong_unreadable_input"] = case("a file in the folder cannot be read when the run starts: survey refuses it plainly, and so does the verdict", "Downloads", save_folder("unreadable", {"Downloads/a.txt": b"a\n", "Downloads/b.txt": b"b\n"}), locked, wrong("Downloads/a.txt cannot be read"))
    cases["wrong_symlink_folder"] = case("the folder holds a symlink to another folder of the member", "Downloads", save_folder("symlink-folder", links, links={"Downloads/linkdir": "../Other"}), refused, wrong("Downloads/linkdir is a symlink"))

    for name, data in cases.items():
        (HERE / f"{name}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    sizes = sum(path.stat().st_size for path in FOLDERS.glob("*.tar.gz"))
    print(f"wrote {len(cases)} cases; folders {sizes} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
