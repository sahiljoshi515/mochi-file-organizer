# File Organizer rules

These rules say exactly what happens to every file in the folder you ask to organize. The plugin's
tools, its answer key and its verifier all apply them with the same code; an independent oracle in
the tests applies them from this text alone.

Paths are relative to the folder and written with `/`. "The name" is a file's own name, never its
folders. Nothing here uses a file's modification time: uploading or copying a file changes it.

## 1. Which files take part

- **Junk** first, by name, ignoring letter case: `.DS_Store`, `Thumbs.db`, `ehthumbs.db`,
  `ehthumbs_vista.db`, `desktop.ini`, `Icon\r`; any name that starts with `._`, `~$` or `.~lock.`;
  any name whose claimed extension (§2) is `tmp`, `part` or `crdownload`. Junk is deleted.
- **Hidden** next: any other name that starts with `.`. Hidden files, and everything inside a hidden
  folder (`.git/`, `.vscode/`, the plugin's own `.file-organizer/`), are left alone and never counted.
- Every other regular file takes part. Archives are never unpacked. A path's depth is its number of `/`.
- **Refused** before anything happens, with a message that says what to fix: a symlink or a special
  file in the folder; more than 1,000 files that take part; more than 200 MiB of them; one over 10 MiB;
  a path deeper than 12 folders or longer than 300 characters; an existing path that differs from a
  path the rules would create only in letter case or Unicode normalization (NFC); a path the rules
  would create as a folder that exists as a file; a result that would leave more than 4,900 files and
  folders in your agent folder (RUSH Lab saves at most 5,000).

## 2. Type and extension: the content decides

The **claimed extension** is the 1 to 10 ASCII letters and digits after the name's last `.`,
lowercased, when that `.` is not the name's first character; otherwise there is none. Files are
sniffed in this order and the first match wins. A match gives a folder pair `<group>/<type>` and an
extension.

| Content | Group/type | Extension |
|---|---|---|
| starts `%PDF-` | documents/pdf | pdf |
| starts with the PNG signature `89 50 4E 47 0D 0A 1A 0A` | images/png | png |
| starts `FF D8 FF` | images/jpg | jpg |
| starts `GIF87a` or `GIF89a` | images/gif | gif |
| `RIFF`, 4 size bytes, then `WEBP` / `WAVE` / `AVI ` | images/webp / audio/wav / video/avi | webp / wav / avi |
| ISO media: bytes 4-7 are `ftyp` | see below | see below |
| starts `II*\0` or `MM\0*` (TIFF) | images/raw when the claimed extension is a raw one, else images/tiff | that raw extension, else tiff |
| starts `FUJIFILMCCD-RAW` | images/raw | raf |
| starts `ID3` and a version byte 2, 3 or 4, or with an MPEG audio frame header (below) | audio/mp3 | mp3 |
| starts `fLaC` / `OggS` | audio/flac / audio/ogg | flac / ogg |
| starts `1A 45 DF A3` (EBML) | video/webm when `webm` occurs in the first 64 bytes, else video/mkv | webm / mkv |
| a zip: starts `PK\3\4` or `PK\5\6` | see below | see below |
| starts `1F 8B` (gzip) | archives/gz | `tar.gz` when the name ends `.tar.gz` or `.tgz` (any case), else gz |
| `ustar` at offset 257 | archives/tar | tar |
| starts `37 7A BC AF 27 1C` | archives/7z | 7z |
| starts `Rar!\x1a\x07` | archives/rar | rar |
| UTF-8 text: an optional BOM and no NUL byte | see below | see below |
| anything else | other/`<ext>` when the claimed extension exists, is not a text extension and is not an extension this table gives (nor `jpeg`, `jpe`, `jfif`, `tif`); else other/bin | that extension, else bin |

- **ISO media brands**: the major brand is bytes 8-11; the compatible brands are the 4-byte groups
  after the minor version (bytes 16 on), up to the end of the `ftyp` box. In this order: major brand
  `avif` or `avis`, or major brand `mif1` or `msf1` with `avif` or `avis` among the compatible brands →
  images/avif `avif`; major brand among `heic heix hevc hevx heim heis mif1 msf1` → images/heic
  `heic`; major brand `qt  ` → video/mov `mov`; major brand `M4A ` or `M4B ` → audio/m4a `m4a`; major
  brand `crx ` → images/raw `cr3`; anything else → video/mp4 `mp4`.
- **Raw extensions**: `dng nef cr2 arw orf rw2 pef srw nrw 3fr erf kdc mos mef iiq`.
- **MPEG audio frame header**: byte 0 is `FF`; in byte 1 the top 3 bits are set, the version bits
  (4-3) are not `01` and the layer bits (2-1) are not `00`; in byte 2 the bitrate bits (7-4) are not
  `1111` and the sample-rate bits (3-2) are not `11`.
- **Zips** are told apart by the names in their central directory: `word/document.xml` →
  documents/docx; `xl/workbook.xml` → spreadsheets/xlsx; `ppt/presentation.xml` →
  presentations/pptx; an entry named `mimetype` whose content is
  `application/vnd.oasis.opendocument.text` → documents/odt, `…opendocument.spreadsheet` →
  spreadsheets/ods, `…opendocument.presentation` → presentations/odp, `application/epub+zip` →
  documents/epub (the extension is the type). The first of these that matches wins. Any other zip
  keeps a claimed extension that is not a text extension and not one this table gives, as
  other/`<ext>` (`.jar`, `.pages`, `.apk`); otherwise it is archives/zip `zip`.
- **Text**: a claimed extension in the text list keeps its group, normalized (`markdown` → `md`,
  `yml` → `yaml`, `htm` → `html`, `ndjson` → `jsonl`); the type is the extension:
  - documents: `txt md rst tex org rtf html`; images: `svg`; spreadsheets: `csv tsv`;
  - data: `json jsonl geojson ipynb xml yaml toml ini cfg conf sql log srt vtt ics vcf bib`;
  - code: `py js mjs cjs ts tsx jsx c h cc cpp hpp cs java kt go rs rb php swift scala lua pl r sh
    bash zsh fish ps1 bat css scss less vue svelte dart proto`.

  Otherwise the content decides, the first match winning. Here `text` is the decoded text without
  its BOM and leading whitespace; `first` is the decoded text's first line; lines are split at `\n`
  with a trailing `\r` dropped. `text` starts `<svg`, or starts `<?xml` and, after the first `?>`
  within its first 4,096 characters and optional whitespace, `<svg` → images/svg; `text` starts
  `<!doctype html` or `<html`, ignoring case → documents/html; `text` starts `{\rtf` →
  documents/rtf; `text` starts `{` or `[` and the whole decoded text parses as JSON → data/json;
  `first` starts `# ` or is `---` → documents/md; at least 3 non-blank lines (a blank line holds
  only whitespace), all with the same number of commas, at least one → spreadsheets/csv; `first`
  starts `YYYY-MM-DD HH:MM:SS` or `YYYY-MM-DDTHH:MM:SS` → data/log; otherwise documents/txt.
- So a JPEG is always `jpg` (never `jpeg`, `jpe` or `jfif`), and a TIFF is `tiff` whether it was
  claimed `tif` or `tiff`.

## 3. Date: embedded, then the name, else undated

A file's date is the first of these that gives a real calendar date:

1. **Embedded**, with a year from 1971 to 2099, taken as stored (no time-zone conversion):

   | Type | Where |
   |---|---|
   | jpg | the first APP1 segment that starts `Exif\0\0`, before the image data: TIFF → IFD0's tag `8769` → the Exif IFD's DateTimeOriginal (tag `9003`, ASCII, `YYYY:MM:DD …`) |
   | tiff, raw that is TIFF | the file itself as TIFF → IFD0's tag `8769` → Exif IFD → tag `9003` |
   | heic, avif | the first item of type `Exif` (the top-level `meta` box → `iinf` → its `iloc` extents, in the file or in `idat`): its first 4 bytes say how many bytes after them the TIFF starts (a leading `Exif\0\0` there is skipped) → Exif IFD → tag `9003` |
   | cr3 | the first `Exif\0\0` followed by a TIFF header within the first 4 MiB → Exif IFD → tag `9003` |
   | webp | the `EXIF` chunk (a leading `Exif\0\0` is skipped) → Exif IFD → tag `9003` |
   | png | the first `eXIf` chunk → its Exif IFD → tag `9003`; else the first `tEXt` chunk with the keyword `Creation Time`, whose text, after optional whitespace, starts `YYYY-MM-DD` or `[Day, ]DD Mon YYYY` (a 3-letter English month, any case) |
   | pdf | the last `/CreationDate` followed by optional whitespace and `(` in the file: the value up to the next `)` (at most 64 bytes), read as `D:YYYYMMDD…` or `YYYYMMDD…` |
   | docx, xlsx, pptx | the zip entry `docProps/core.xml`: the text of the first element written `dcterms:created`, after optional whitespace, starting `YYYY-MM-DD` |
   | odt, ods, odp | the zip entry `meta.xml`: the text of the first element written `meta:creation-date`, after optional whitespace, starting `YYYY-MM-DD` |
   | mp4, mov, m4a | the first top-level `moov` box, the first `mvhd` box in it: its creation time, seconds since 1904-01-01 UTC (0 means none) |
   | md | front matter: when the first line is exactly `---`, the first line that starts `date:` before a line that is `---` (spaces around it allowed); its value, trimmed of spaces and tabs and then of quotes, starting `YYYY-MM-DD` |

2. **The name**: a name in scheme form (§4) gives its date part (a year from 1971 to 2099); any other
   name gives the first `YYYY?MM?DD` in the name without its extension, where `?` is the same one of
   `-`, `_`, `.` or nothing in both places, not touching other digits, with a year from 1990 to 2039.
3. Otherwise the file is **undated**.

Out of scope, giving no embedded date: XMP, compressed PDF object streams, PDF dates written in hex or
UTF-16, `zTXt` and `iTXt`, PNG `tIME`, ID3 years, QuickTime `©day`, EPUB dates, HTML meta dates, zip
methods other than stored and deflate, ZIP64, and encrypted zip entries.

## 4. Name and place

- **Scheme form**: `<date>_<slug>[_<n>].<ext>`, where `<date>` is `YYYY-MM-DD` or `undated`, `<slug>`
  is lowercase letters and digits in hyphen-joined words, `<n>` is 2 or more, and `<ext>` is `tar.gz`
  or 1 to 10 lowercase letters and digits. A name in scheme form keeps its slug, so organizing an
  organized folder changes nothing.
- **Slug** of any other name, from the name without its extension (without `.tar.gz` or `.tgz` for a
  `tar.gz`), in this order:
  1. remove the date §3 step 2 reads from the name, whether or not the file's date came from it;
  2. Unicode NFKD, keeping ASCII characters only; then lowercase;
  3. strip a leading `copy of `, repeatedly;
  4. strip from the end, repeatedly until none is left, any of these (where "space" is one or more
     whitespace characters): optional space, `(`, digits, `)`; space, `-`, space, `copy`, optionally
     followed by space, `(`, digits, `)`; space and `copy`, optionally followed by space and digits;
     `_` or `-`, then `copy`, then optional digits;
  5. turn every run of characters other than `a-z0-9` into one `-` and trim `-` from both ends;
  6. keep at most 60 characters and trim a trailing `-`; an empty slug is `file`.
- **Base path**: `organized/<group>/<type>/<YYYY>/<YYYY-MM-DD>_<slug>.<ext>`, or
  `organized/<group>/<type>/undated/undated_<slug>.<ext>` for an undated file.
- A file **conforms** when it sits at its base path, or at its base path with `_<n>` (n ≥ 2) before
  the extension.

## 5. The plan

- **Order**: conforming files first, then all others; each part sorted by path (as the file system
  spells it), comparing characters by code point. A file's number `i` is its place in this order, from
  0.
- Every path that exists in the folder when the run starts is **taken**. Walk the files in order:
  1. junk → **delete** (junk);
  2. an empty file → **delete** (empty);
  3. the same bytes (sha256) as an earlier file that is kept → **delete** (copy): the earliest copy in
     the order is the one kept;
  4. a conforming file → **stays**;
  5. any other file → **moves** to the first of `base`, `base_2`, `base_3`, … that is not taken
     (comparing paths ignoring letter case and Unicode normalization), and takes it.
- **One run does at most 60 actions** (moves and deletes): the first 60 in the order. The rest wait for
  the next run, where the same rules start again from the folder as it is then. Folders left empty
  inside the folder are removed.
