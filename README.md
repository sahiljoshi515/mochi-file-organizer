# File Organizer

A `nanoagent.plugin/v1` plugin for NanoAgent 0.5, with the structure of the reference plugin,
[arxiv-source](https://github.com/zeyuyang8/arxiv-source). Its task, `organize-folder`, tidies a folder
of the member's own files: an agent deletes exact duplicates, junk and empty files and files every
other file under `organized/<group>/<type>/<YYYY>/<YYYY-MM-DD>_<slug>.<ext>` by the rules in
[src/plugin/RULES.md](src/plugin/RULES.md). A static, rule-based verifier (no model anywhere) compares
the folder after the run with an answer key pinned before it, hash by hash and path by path, re-reads
every file in place to check that it follows the rules for its own bytes, and checks that everything
the rules leave alone (hidden entries, everything outside the folder) is exactly as it was.

## Tools

| Tool | Does | Code |
|---|---|---|
| `pin_layout` | Reads every file in a copy of the agent folder taken before the agent starts, applies the rules and pins each file's facts (sha256, sniffed type, embedded or named date, slug, base path) and the step the rules give it, plus a snapshot (path, size, sha256) of everything the run must leave as it was; the task's answer key, which the agent never sees | `src/plugin/organizer.py` |
| `survey` | Lists this run's files to act on: the first 60 actions in the rules' order, each with its number `i`, the start of its sha256 (`h`), where the rules file it (`base`) and whether to drop it (`junk`, `empty`, or `copy` of a file already in place). The first call of a run fixes the rows and removes the folder's empty folders; later calls repeat the rows with the run's summary so far | `src/plugin/organizer.py` |
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
| 4 | `plain-entries` | The agent folder holds only files and folders the rules can read: no symlink, special file or unreadable entry (otherwise the verdict says the rules refuse the folder, and checks nothing else) |
| 5 | `every-file-kept` | Every content the folder must keep still exists somewhere in it |
| 6 | `moved-to-rules-path` | Every file this run moves holds its bytes at exactly the path the rules give it |
| 7 | `duplicates-and-junk-removed` | Every duplicate, junk and empty file this run deletes is gone |
| 8 | `others-untouched` | Every file this run does not act on is where it was, byte for byte |
| 9 | `hidden-untouched` | Every hidden file and folder in the folder is as the snapshot pinned it, and none is new |
| 10 | `outside-untouched` | Everything in the agent folder outside the folder is as pinned, and nothing is new there (the run state aside) |
| 11 | `nothing-extra` | The folder holds no other file (no copies left behind, no strays) and no empty folder |
| 12 | `organized-by-rules` | Every file in place follows the rules when re-read from its own bytes |
| 13 | `summary-matches` | The submitted summary's counts match the folder (moved = new paths, deleted, left, stayed, remaining) |
| 14 | `saved-back` | The agent folder holds fewer than 5,000 entries, so RUSH Lab saves the result |

Score = hits / (hits + misses): hits are this run's moves at their path and deletes done; misses are
every path that differs in checks 6-12, counted once, plus one per failed check 2, 13 or 14. A failed
check 1, 3 or 4 scores 0.

## The rules

[src/plugin/RULES.md](src/plugin/RULES.md) is the whole specification, and the only thing the
independent oracle in `tests/oracle/` is written from. In short:

- Junk (`.DS_Store`, `Thumbs.db`, `._*`, `~$*`, `.tmp`, `.part`, `.crdownload`, …) and empty files are
  deleted; hidden files and folders (`.git/`, …) and everything outside the folder are left exactly as
  they were; empty folders are removed.
- The **content** decides the type, never the name: about 40 real formats (PDF, PNG, JPEG, GIF, WebP,
  HEIC, AVIF, TIFF and camera raw, MP3, FLAC, OGG, WAV, MP4, MOV (also classic QuickTime), M4A, WebM,
  MKV, AVI, MPEG-TS, the Office family (docx, docm, dotx, xlsx, xlsm, xltx, xlsb, pptx, pptm, ppsx, …),
  odt, ods, odp, epub, zip, gz, tar, 7z, rar, and text in UTF-8, UTF-16, UTF-32 or Windows-1252, by
  its extension or its content).
- The **date** is the one embedded in the file (EXIF, CR3 metadata, PNG text, the PDF's document
  information, Office and OpenDocument properties, the MP4/MOV movie header, Markdown front matter),
  else a date in the name, else `undated`. Modification times are never used: uploading a file
  changes them.
- Exact duplicates (same sha256) keep one copy: the first in the rules' order, which puts files in
  place first, then names without a copy marker (`(1)`, ` copy`, `Copy of `), then names whose
  extension is their type's, then the shallowest path. A name already taken gets `_2`, `_3`, …; a name
  already in scheme form keeps its slug, so organizing an organized folder changes nothing.

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
verifier/              verify_input, verify_output, verify_task (task.py: the 14 constraints), plus
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
FILE_ORGANIZER_PERF=1 uv run pytest -m perf   # every verifier call at the published limits, timed
uv run ruff check .
```

Run the task exactly as NanoAgent does, with a scripted agent instead of a model, through the lab's
harness (`scripted_task.py` and `run_cases.py` from the RUSH Lab plugin tooling, run with NanoAgent's
Python):

```bash
python scripted_task.py . tests/cases/gold_small.json --sandbox seatbelt   # one case
python run_cases.py . tests/cases --jobs 4 --sandbox seatbelt              # all 40, with timings
uv run python tests/corpus/real_cases.py /tmp/real-cases 9                 # cases on real-file folders
python run_cases.py . /tmp/real-cases --sandbox seatbelt
```

Each case unpacks an agent folder (`tests/cases/folders/*.tar.gz`), lets the reference pin the answer
key from a copy of it, then runs `survey`, a python step that decides the rows exactly as the
instructions say (`tests/cases/agent.py`), `apply` twice and `submit`. The 12 gold cases must be valid
at 1.0; each of the 28 wrong cases makes one mistake (keeping the wrong copy, moving a duplicate,
swapping collision numbers, skipping a call, moving junk, a false summary, tampering, a stray file, a
copy left behind, a number outside the run; and the review's red team: hidden entries changed, removed
or added, files outside the folder changed or added, empty folders left, a FIFO, an unreadable file, a
symlink in the folder, a duplicate or a folder stashed at the run state's path) and must fail the constraint it breaks. `tests/test_cases.py` replays them all
without NanoAgent. `tests/cases/build_cases.py` rebuilds every case and its folder from the
builders, deterministically.

The real-file corpus (`tests/corpus/sources.json`: 38 files, 2.5 MB) comes from the Pillow and
pillow-heif test images, Apache POI, LibreOffice, web-platform-tests, Project Gutenberg, pdf.js, the IRS,
CPython, Data Packages, the Jekyll docs and PyPI; each keeps its own licence, listed per file, and is
downloaded at test time, never committed.

## Limitations

- One run does at most 60 actions; larger folders take several runs (the verdict says how many remain).
- A folder is refused when it holds more than 1,000 files, 200 MiB, a file over 10 MiB, paths deeper
  than 12 folders or longer than 300 characters, case or Unicode variants of the folders the rules
  create, or would leave more than 4,900 entries in the agent folder; and when the agent folder holds
  a symlink, a special file or an unreadable entry anywhere, or more than 1 GiB (the verifier reads it
  all to check that the run left it as it was).
- Dates come only from the metadata RULES.md lists (no XMP, no PDF information inside compressed
  object streams, no ID3 or QuickTime text dates); RW2, ORF, RAF and other raw files that are not
  TIFF-shaped are undated unless their name carries a date. Text in legacy encodings other than
  Windows-1252 (Shift-JIS, MacRoman, …) is not recognized as text.
- Every structure is read only so far (RULES.md §3, "Reading limits"): a zip part's first 4,096 bytes
  and 4 DEFLATE blocks, a JPEG's first 64 markers, 1,024 PNG/RIFF chunks or ISO boxes, the first 1,000
  lines of text. A date beyond them is not found. In exchange the verifier, which re-derives every
  file's facts and runs each check twice within NanoAgent's 60 s, takes at most about 13 s per call at
  the limits (1,000 files, 200 MiB, a 1 GiB agent folder) on the development Mac, in the costliest
  folder we could build (dense Office metadata in 982 files, 10 MiB JSON texts in the rest):
  `tests/test_perf.py` holds every call under 20 s.
- Embedded dates are taken as stored, with no time-zone conversion.
