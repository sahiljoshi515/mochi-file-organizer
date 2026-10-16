# File Organizer

A `nanoagent.plugin/v1` plugin for NanoAgent 0.5, with the structure of the reference plugin,
[arxiv-source](https://github.com/zeyuyang8/arxiv-source). Its task, `organize-folder`, tidies a folder
of the member's own files: an agent deletes exact duplicates, junk and empty files and files every
other file under `organized/<group>/<type>/<YYYY>/<YYYY-MM-DD>_<slug>.<ext>` by the rules in
[src/plugin/RULES.md](src/plugin/RULES.md). A static, rule-based verifier (no model anywhere) compares
the folder after the run with an answer key pinned before it, hash by hash and path by path, and
re-reads every file in place to check that it follows the rules for its own bytes.

## Tools

| Tool | Does | Code |
|---|---|---|
| `pin_layout` | Reads every file in a copy of the agent folder taken before the agent starts, applies the rules and pins each file's facts (sha256, sniffed type, embedded or named date, slug, base path) and the step the rules give it; the task's answer key, which the agent never sees | `src/plugin/organizer.py` |
| `survey` | Lists this run's files to act on: the first 60 actions in the rules' order, each with its number `i`, the start of its sha256 (`h`), where the rules file it (`base`) and whether to drop it (`junk`, `empty`, or `copy` of a file already in place). The first call of a run fixes the rows; later calls repeat them with the run's summary so far | `src/plugin/organizer.py` |
| `apply` | Deletes rows by `i` and moves rows `{i, n}` to the n-th free name of their base (`base`, `base_2`, …), in this run's rows only, after checking each file's bytes; a refused item is reported and the others are done; it never deletes the last copy of any content and removes folders left empty | `src/plugin/organizer.py` |

### Tasks

| Task | Does | Runner |
|---|---|---|
| `organize-folder` | Tidies the member's folder by the rules and submits the run's summary (an `OrganizeOutput`) | `agent`, with `survey` and `apply`; reference `pin_layout` |

The tools work out what one file says about itself: its type from its bytes, its date from its
metadata or its name, its slug and its base path. The agent makes the decisions that take several
files: which copy of duplicated bytes stays (the earliest in the rules' order), which collision number
each file gets, the batches, and repairing anything a call refuses. (All three live runs of version
0.1.1, which asked the hosted model to derive every date and slug itself, ran out of reply tokens.)

### Using it

Upload the files to organize into your File Organizer agent folder on RUSH Lab (for example into a
folder `Downloads`), open the plugin and ask its chat, e.g. "organize my Downloads folder". The chat
runs `organize-folder` with `{"folder": "Downloads"}` (`.` means the whole agent folder). The folder is
tidied in place: afterwards it holds `organized/` plus anything hidden, and RUSH Lab saves the result
back to your agent folder.

A hosted run allows 6 agent steps and about 2,000 output tokens per reply, so one run does at most 60
actions: `survey`, `apply` for the first 30 rows, `apply` for the rest, a spare step for errors, and
`submit`. A folder that needs more says so ("N more: ask again to continue"): ask again and the next run
carries on from the folder as it is, with the same rules.

## Constraints

`verify_task` checks these in order and lists every one in `details.constraints`
(`{id, constraint, ok, expected, actual, message}`; `ok` is null when an earlier failure means it was
not checked). The verdict is valid only when all hold, and only then is the score 1.0.

| # | id | Holds when |
|---|---|---|
| 1 | `answer-key` | The pinned answer key is for this folder and is exactly the rules applied to its pinned facts |
| 2 | `submitted-folder` | The submitted result names the folder the task asked for |
| 3 | `folder-present` | The folder is still in the agent folder |
| 4 | `every-file-kept` | Every content the folder must keep still exists somewhere in it |
| 5 | `moved-to-rules-path` | Every file this run moves holds its bytes at exactly the path the rules give it |
| 6 | `duplicates-and-junk-removed` | Every duplicate, junk and empty file this run deletes is gone |
| 7 | `others-untouched` | Every file this run does not act on is where it was, byte for byte |
| 8 | `nothing-extra` | The folder holds no other file (no copies left behind, no strays, no symlinks) |
| 9 | `organized-by-rules` | Every file in place follows the rules when re-read from its own bytes |
| 10 | `summary-matches` | The submitted summary's counts match the folder (moved = new paths, deleted, left, stayed, remaining) |
| 11 | `saved-back` | The agent folder holds fewer than 5,000 entries, so RUSH Lab saves the result |

Score = hits / (hits + misses): hits are this run's moves at their path and deletes done; misses are
every path that differs in checks 5-9, counted once, plus one per failed check 2, 10 or 11. A failed
check 1 or 3 scores 0.

## The rules

[src/plugin/RULES.md](src/plugin/RULES.md) is the whole specification, and the only thing the
independent oracle in `tests/oracle/` is written from. In short:

- Junk (`.DS_Store`, `Thumbs.db`, `._*`, `~$*`, `.tmp`, `.part`, `.crdownload`, …) and empty files are
  deleted; hidden files and folders (`.git/`, …) are left alone.
- The **content** decides the type, never the name: about 35 real formats (PDF, PNG, JPEG, GIF, WebP,
  HEIC, AVIF, TIFF and camera raw, MP3, FLAC, OGG, WAV, MP4, MOV, M4A, WebM, MKV, AVI, docx, xlsx,
  pptx, odt, ods, odp, epub, zip, gz, tar, 7z, rar, and text by its extension or content).
- The **date** is the one embedded in the file (EXIF, PNG text, PDF, Office and OpenDocument
  properties, the MP4 movie header, Markdown front matter), else a date in the name, else `undated`.
  Modification times are never used: uploading a file changes them.
- Exact duplicates (same sha256) keep their earliest copy in the rules' order; a name already taken
  gets `_2`, `_3`, …; a name already in scheme form keeps its slug, so organizing an organized folder
  changes nothing.

## Layout

```
contract.py            every tool's and the task's input and output classes
nanoagent.yaml         the manifest: tools, the organize-folder task and its instructions
src/plugin/
  RULES.md             the rules, in words
  organizer.py         the tools: pin_layout, survey, apply (the run's state, safe moves and deletes)
  naming.py sniff.py meta.py formats.py inflate.py walk.py plan.py layout.py
                       the rules in code (shared, byte for byte, with verifier/)
  __main__.py          the MCP server
verifier/              verify_input, verify_output, verify_task (task.py: the 11 constraints), plus
                       byte-identical copies of the rule modules
ui/renderers.js        draws OrganizeOutput with the verifier's checks and this run's files
tests/                 unit, property, oracle-differential, server and replay tests; tests/cases/
                       holds the scripted cases and the folders they run on
```

The plugin reaches no network host and writes only in the workspace: the folder itself and
`.file-organizer/state.json`, the run's state (its rows and every move and delete), which the
verifier checks after each call.

## Develop and run

```bash
uv sync --extra dev
uv run pytest                       # offline: unit, property, differential and replay tests
uv run python tests/corpus/fetch.py # optional: download the real-file corpus (licences in tests/corpus/sources.json)
uv run pytest -m corpus             # the same checks on folders built from real files
uv run ruff check .
```

Run the task exactly as NanoAgent does, with a scripted agent instead of a model, through the lab's
harness (`scripted_task.py` and `run_cases.py` from the RUSH Lab plugin tooling, run with NanoAgent's
Python):

```bash
python scripted_task.py . tests/cases/gold_small.json --sandbox seatbelt   # one case
python run_cases.py . tests/cases --jobs 4 --sandbox seatbelt              # all 19, with timings
uv run python tests/corpus/real_cases.py /tmp/real-cases 9                 # cases on real-file folders
python run_cases.py . /tmp/real-cases --sandbox seatbelt
```

Each case unpacks an agent folder (`tests/cases/folders/*.tar.gz`), lets the reference pin the answer
key from a copy of it, then runs `survey`, a python step that decides the rows exactly as the
instructions say (`tests/cases/agent.py`), `apply` twice and `submit`. The 9 gold cases must be valid at
1.0; each of the 10 wrong cases makes one mistake (keeping the wrong copy, moving a duplicate, swapping
collision numbers, skipping a call, moving junk, a false summary, tampering, a stray file, a copy left
behind, a number outside the run) and must fail the constraint it breaks. `tests/test_cases.py` replays
them all without NanoAgent. `tests/cases/build_cases.py` rebuilds every case and its folder from the
builders, deterministically.

The real-file corpus (`tests/corpus/sources.json`: 38 files, 2.5 MB) comes from the Pillow and
pillow-heif test images, Apache POI, LibreOffice, web-platform-tests, Project Gutenberg, pdf.js, the IRS,
CPython, Data Packages, the Jekyll docs and PyPI; each keeps its own licence, listed per file, and is
downloaded at test time, never committed.

## Limitations

- One run does at most 60 actions; larger folders take several runs (the verdict says how many remain).
- A folder is refused when it holds more than 1,000 files, 200 MiB, a file over 10 MiB, a symlink,
  paths deeper than 12 folders or longer than 300 characters, case or Unicode variants of the folders
  the rules create, or would leave more than 4,900 entries in the agent folder.
- Dates come only from the metadata RULES.md lists (no XMP, no compressed PDF object streams, no ID3
  or QuickTime text dates); camera raw files other than TIFF-based ones, Fuji RAF and Canon CR3
  without an Exif block are undated unless their name carries a date.
- Embedded dates are taken as stored, with no time-zone conversion.
