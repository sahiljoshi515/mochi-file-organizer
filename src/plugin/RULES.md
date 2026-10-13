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
null), `mtime_utc` (`YYYY-MM-DDTHH:MM:SSZ`). `unpack_inbox` returns the first page of the
inventory with these rules; `inventory` returns any page.
