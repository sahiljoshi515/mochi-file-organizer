# File Organizer

A `nanoagent.plugin/v1` plugin, created by `nanoagent plugin new` with the
structure of NanoAgent's reference plugin, `plugins/arxiv-source`. Its task,
`organize`, hands an agent a messy folder made from a seed (duplicates under
other names, junk, empty and misnamed files, dates hiding in metadata) and asks
it to delete what the rules delete and move every other file to
`organized/<category>/<YYYY>/<YYYY-MM-DD>_<slug>.<ext>`. The verifier compares
the result, hash by hash and path by path, with the layout the rules give.

## Tools

| Tool | Does | Code |
|---|---|---|
| `pin_inventory` | Makes the messy folder in the reference's scratch workspace, applies the rules, and pins every kept file's sha256 and final path with the counts; the `organize` task's reference | `src/plugin/organizer.py` |
| `unpack_inbox` | Makes the messy folder for `seed` and `size` at `file-organizer/<seed>-<size>/inbox/` and an empty `organized/`, and returns the rules; idempotent: an untouched folder gives the same answer again, a folder already worked on is left as it is (`complete: true`) | `src/plugin/organizer.py` |
| `read_rules` | Returns `src/plugin/RULES.md`, the rules below, verbatim (the same text `unpack_inbox` returns) | `src/plugin/organizer.py` |
| `inventory` | One page (at most 100 rows) of every file under the folder, sorted by path: its number `i`, size, sha256, sniffed type, claimed extension, the raw embedded dates (`exif`, `png`, `pdf`, `md`) and `mtime_utc`; nothing normalized | `src/plugin/organizer.py` |
| `apply_plan` | Moves (`{i, dst}`, `dst` under `organized/`) then deletes (by number) files inside the folder, at most 80 of each per call: confined to it, files only, never overwriting; an unknown or spent number, like any other failed item, is reported and the rest still applied; empty folders are pruned | `src/plugin/organizer.py` |
| `list_tree` | The folder's files and sub-folders, sorted, at most 200 entries | `src/plugin/organizer.py` |

The generator (`src/plugin/generate.py`) builds every byte itself from one
`random.Random(f"file-organizer:v1:{seed}:{size}")`: JPEGs from five tiny
fixtures in `src/plugin/data/jpeg/` with an EXIF `DateTimeOriginal` segment
made by Pillow, PNGs chunk by chunk with a `Creation Time` text chunk, minimal
PDFs with `/CreationDate`, stored DOCX and ZIP archives with fixed dates, and
SVG, HTML, Python, JSON, CSV, log, Markdown (with front matter), text and
opaque binary files. Sizes: small 60, medium 150, large 300 files. About 55 %
are unique, 25 % extra copies of a file under other names (`Copy of`, `(1)`,
`- Copy`, `_v2`, upper-case, wrong or missing extensions), 8 % near-duplicates
(same name and size, different bytes), 6 % junk, 3 % empty, 3 % name collisions;
12 % of the names claim the wrong type, 40 % carry a date (some invalid), and
names use accents, spaces and other scripts. Files sit in 8 to 25 folders (a
small folder: 8 to 10, at most two deep, with short names), some empty, each
with its own modification time.

### The task

`organize` takes `{seed, size}`. NanoAgent first runs `pin_inventory` in a
scratch workspace and pins the layout the rules give. The agent then calls
`unpack_inbox` (which also returns the rules), `inventory` page by page (100
rows each), and `apply_plan` in batches of up to 80 moves and 80 deletes, each
file named by its inventory number `i`; `read_rules` returns the rules again
if needed. A file's number is given once, from the first full listing of the
folder, and stays with it when it moves (the numbers are kept in the plugin
process and recorded beside the folder as `file-organizer/<seed>-<size>.ids.json`).
The tools never normalize a date, sniff a duplicate or choose a name for it.
Everything the agent decides, it decides from the inventory rows and the rules.

Budget: Mochi's hosted runner allows 6 agent steps per run and 2048 tokens
per reply, hidden reasoning included, so `small` is designed to take 4 tool
calls and the answer: `unpack_inbox`, one `inventory` page, and `apply_plan`
twice, first for the files numbered 0 to 29 and then for the rest, so that each
reply only has to think about 30 files (the whole plan would fit one call: its
arguments measure about 1100 tokens, and the folders stay shallow with short
names). Destinations are still decided over the whole inventory: a duplicate's
keeper and a collision's suffixes follow the rules whatever batch a file is
applied in, and a delete may go in either batch. Medium and large need a
runner with a higher step limit, such as the member's own computer: their
inventories are 2 and 3 pages and their plans several batches.

### The rules

The text below is `src/plugin/RULES.md`, what `read_rules` returns.

# File Organizer rules

Every file under `inbox/` is either deleted or moved to
`organized/<category>/<YYYY>/<YYYY-MM-DD>_<slug>.<ext>`. When you are done, `inbox/` holds no
files and `organized/` holds nothing but the kept files. Paths are relative to the task's root.

## 1. Delete

- Junk, by name: `.DS_Store`, `Thumbs.db`, `desktop.ini` (in any letter case), any name starting
  with `~$`, and any claimed extension `tmp` or `part` (in any letter case).
- Empty files (size 0).
- Exact duplicates: files with the same `sha256` are one file. Keep the copy with the earliest
  `mtime_utc`; on a tie, the smallest `path` (plain string order). Delete every other copy. The
  same name or the same size never makes a duplicate; only the hash does.

## 2. Category and extension: by content, never by the name

The inventory's `type` is sniffed from the bytes, in this order: `pdf` (`%PDF-`), `png`, `jpg`
(JPEG), `docx` (a zip holding `word/document.xml`), `zip`, `svg` (`<svg` after an optional XML
declaration), `html` (`<!DOCTYPE html` or `<html`), `py` (a `#!` first line naming python),
`json` (parses, starting with `{` or `[`), `log` (first line starts with `YYYY-MM-DD HH:MM:SS` or
`YYYY-MM-DDTHH:MM:SS`), `md` (first line is a `# ` heading or `---`), `csv` (3 or more lines,
every line the same number of commas, at least one), `txt` (any other UTF-8 text), `bin`
(anything else).

| type | category | ext |
|---|---|---|
| pdf | documents/pdf | pdf |
| png | images/png | png |
| jpg | images/jpg | jpg |
| docx | documents/docx | docx |
| zip | archives/zip | zip |
| svg | images/svg | svg |
| html | documents/html | html |
| py | code/py | py |
| json | data/json | json |
| log | logs/log | log |
| md | documents/md | md |
| csv | data/csv | csv |
| txt | documents/txt | txt |
| bin | other/bin | bin |

The claimed extension (`ext`) is ignored: a JPEG named `.JPEG`, `.png` or `.txt` becomes `.jpg`.

## 3. Date: the first of these that gives a real calendar date

1. An embedded value, as the inventory reports it: `exif` (EXIF DateTimeOriginal,
   `YYYY:MM:DD HH:MM:SS`, so its first ten characters with `:` turned into `-`), else `png`
   (PNG Creation Time: `YYYY-MM-DD...`, or RFC 1123 `Day, DD Mon YYYY HH:MM:SS GMT`, whose day,
   month and year give the date), else `pdf` (`D:YYYYMMDD...`: the eight digits after `D:`),
   else `md` (the front-matter `date` value, with or without quotes, whose first ten characters
   are `YYYY-MM-DD`). A value that is not a real date (month 13, day 31 of April) is skipped.
2. Else the file's own name (folder names do not count): the first `YYYY-MM-DD` or `YYYYMMDD`
   that is not touching other digits, is a real date and has a year from 1990 to 2030.
3. Else the date part of `mtime_utc`.

## 4. Slug: from the kept copy's own name

Take the name without its claimed extension (an extension is 1 to 10 letters or digits after the
last `.`, when that `.` is not the first character). Then: normalize to NFKD and drop every
non-ASCII character; lowercase; strip copy markers from the end, again and again until nothing
matches, with the regular expression
`(\s*\(\d+\)|\s*-\s*copy(\s*\(\d+\))?|[\s_-]+copy\d*|[-_ ]?(final|v\d+))$`; turn every run of
characters other than `a-z` and `0-9` into one `-`; trim `-` from both ends. If nothing is left,
the slug is `file`.

## 5. Collisions

Name the kept files in `(mtime_utc, path)` order. When a file's path is already taken, append `-2`
to its slug, then `-3`, and so on, to the first free path.

## Inventory columns

`i` (the file's number, the same for the whole task even after it moves: `apply_plan` moves and
deletes files by it), `path` (relative to root), `size` (bytes), `sha256`, `type` (sniffed), `ext`
(as the name claims; empty for none), `exif`, `png`, `pdf`, `md` (the raw embedded values, or
null), `mtime_utc` (`YYYY-MM-DDTHH:MM:SSZ`).

### Verifier

`verifier/rules.py` implements the rules once, with only what a verifier may
import; `src/plugin/rules.py` is its byte-identical copy (a test asserts it), so
the reference, the inventory and the checks all run the same code. The
verifier reads the EXIF segment, the PNG chunks, the PDF info dictionary and
the zip central directory by hand, and computes UTC dates by arithmetic.

- `verify_output` of `pin_inventory` recomputes the whole plan from the files
  the tool made in its scratch workspace and demands the pinned layout and
  counts equal it; of `inventory`, that the page equals the rules' own reading
  of the folder and each number matches the folder's record; of `apply_plan`,
  that every item not reported as failed has happened (the moved file is at its
  destination under its number, the deleted one is gone); of `unpack_inbox` and
  `list_tree`, the counts on disk.
- `verify_task` walks the folder: `inbox/` and everything outside `organized/`
  must hold no file; every file under `organized/` is hashed; each pinned
  sha256 must sit exactly once at exactly its pinned path; nothing else may be
  there; every path must be one the rules could give. The score is the share of
  pinned files in place; the verdict is valid only when everything holds.
  Details list the missing, misplaced, duplicate, extra and leftover files and
  the odd names, so the page can show a mismatch table.

Scripted gold cases under `tests/cases/` run the small folder both as one
`apply_plan` call and as the two batches by number the instructions prescribe,
and the medium and large folders in batches. Adversarial cases, each a test in
`tests/test_verifier.py` and a scripted case under `tests/cases/`: duplicates
moved instead of deleted, a unique
near-duplicate deleted, a copy rewritten with different bytes, types taken
from the extension, the wrong copy kept, collisions ordered by name, junk or
empty files kept, dedup by size and name, files left in the inbox, and a
name date used over embedded metadata.

## Layout

```text
.
├── nanoagent.yaml   # manifest (a slimconfig ManifestConfig): id, runtime, permissions, tools, tasks
├── contract.py      # each tool's and task's typed input and output: slimconfig Output classes
├── README.md
├── LICENSE
├── pyproject.toml
├── uv.lock
├── .gitignore
├── .env             # environment variable NAMEs this plugin needs (none here)
├── run.sh           # exits 0 when this environment can run the plugin
├── src/plugin/      # the MCP server (__main__.py), the tools, the generator, RULES.md, rules.py, data/
├── tests/           # unit tests, and scripted gold and wrong cases under tests/cases/
├── ui/              # the page: app.js, organizer.js (its logic), app.css
└── verifier/        # deterministic verifier package: rules.py and one module per tool
```

`contract.py` types every value: the server builds each call's input into its
class and checks its output against its own, and NanoAgent and the verifier
get the same classes. `verifier/` imports only the standard library and
`contract`. Its input checks hold what a type cannot: a seed between 0 and
999999999, a root of the form `file-organizer/<seed>-<size>`, pages of 1 to
100 rows, at most 80 moves and 80 deletes per call, listings of 1 to 200
entries, and plan paths that stay inside the folder.

## Develop and run

```bash
uv sync --extra dev
uv run pytest
```

From the NanoAgent repository root:

```bash
.venv/bin/nanoagent plugin inspect plugins/file-organizer
```

Scripted gold and wrong runs through NanoAgent's own task runner, with the
harness in `~/mochi-dev/harness`:

```bash
<nanoagent venv>/bin/python ~/mochi-dev/harness/scripted_task.py . tests/cases/gold_small.json
```
