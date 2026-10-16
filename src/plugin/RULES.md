# File Organizer rules

These rules say exactly what happens to every file in the folder you ask to organize. The plugin's
tools, its answer key and its verifier all apply them with the same code; an independent oracle in
the tests applies them from this text alone.

Paths are relative to the folder and written with `/`, spelled as the file system lists them. "The
name" is a file's own name, never its folders. Nothing here uses a file's modification time:
uploading or copying a file changes it. A "space" is one or more whitespace characters. The folder
is named as your agent folder lists it, letter case included (when no name is spelled exactly so, the
one name equal to it in Unicode NFC form names it); `.` names your whole agent folder.

## 1. Which files take part, and what is never touched

- **Junk** first, by a file's name, ignoring letter case: `.DS_Store`, `Thumbs.db`, `ehthumbs.db`,
  `ehthumbs_vista.db`, `desktop.ini`, `Icon\r`; any name that starts with `._`, `~$` or `.~lock.`;
  any name whose claimed extension (§2) is `tmp`, `part` or `crdownload`. Junk is deleted.
- **Hidden** next: any other file whose name starts with `.`, and any folder whose name starts with
  `.`. A hidden file, a hidden folder and everything inside a hidden folder (`.git/`, `.vscode/`, …,
  junk names included) is **left exactly as it was**: never moved, changed or deleted, and no new
  hidden file or folder may appear anywhere in the folder.
- **Everything outside the folder** in your agent folder is also left exactly as it was, and nothing
  new may appear there. The one exception is the plugin's own run state,
  `.file-organizer/state.json` at the top of your agent folder, which the plugin writes and rewrites,
  and the `.file-organizer/` folder that holds it; anything else in that folder is left exactly as it
  was too.
- Every other regular file in the folder takes part. Archives are never unpacked. A path's depth is
  its number of `/`.
- **Refused** before anything happens, with a message that says what to fix:
  - a symlink, or anything that is neither a regular file nor a folder (a FIFO, a socket, a device),
    anywhere in your agent folder, `.file-organizer/` included;
  - a file or folder there that cannot be read: a file whose owner may not read it, a folder whose
    owner may not open it (read and search), or anything whose reading fails;
  - a `.file-organizer` at the top of your agent folder that is not a folder;
  - a `.file-organizer/state.json` that is not this plugin's run state (a regular file of at most 16 MiB
    holding a JSON object, nested at most 512 deep, with the fields `version`, `token`, `folder`,
    `hash_length`, `taken`, `rows`, `applied`, `calls` and `summary`), because the plugin would
    overwrite it;
  - more than 1,000 files that take part, more than 200 MiB of them, or one over 10 MiB;
  - more than 1 GiB in your whole agent folder (every file there is read to check the run);
  - a file that takes part deeper than 12 folders, or with a path longer than 300 characters
    counted from your agent folder (the folder's own path and its `/` included);
  - an existing path that differs from a folder this run creates only in letter case or Unicode
    normalization (NFC), or a file standing where this run needs a folder;
  - a result that would leave more than 4,900 files and folders in your agent folder (RUSH Lab saves
    at most 5,000);
  - a folder with no file that takes part.

## 2. Type and extension: the content decides

The **claimed extension** is the 1 to 10 ASCII letters and digits after the name's last `.`,
lowercased, when that `.` is not the name's first character; otherwise there is none. The
**normalized** claimed extension maps `markdown` → `md`, `yml` → `yaml`, `htm` → `html`, `ndjson` →
`jsonl`, `jpeg`/`jpe`/`jfif` → `jpg`, `tif` → `tiff`; every other extension is itself. Files are sniffed
in this order and the first match wins. A match gives a folder pair `<group>/<type>` and an extension.

| # | Content | Group/type | Extension |
|---|---|---|---|
| 1 | starts `%PDF-` | documents/pdf | pdf |
| 2 | starts with the PNG signature `89 50 4E 47 0D 0A 1A 0A` | images/png | png |
| 3 | starts `FF D8 FF` | images/jpg | jpg |
| 4 | starts `GIF87a` or `GIF89a` | images/gif | gif |
| 5 | `RIFF`, 4 size bytes, then `WEBP` / `WAVE` / `AVI ` | images/webp / audio/wav / video/avi | webp / wav / avi |
| 6 | ISO media: bytes 4-7 are `ftyp` | see below | see below |
| 7 | classic QuickTime: bytes 4-7 are `moov`, `mdat`, `wide`, `free`, `skip` or `pnot`, and the box size fits the file: bytes 0-3 (big-endian) are 0, or 1 with a 64-bit size in bytes 8-15 from 16 to the file's length, or from 8 to the file's length | video/mov | mov |
| 8 | starts `II*\0` or `MM\0*` (TIFF) | images/raw when the claimed extension is a raw one, else images/tiff | that raw extension, else tiff |
| 9 | starts `FUJIFILMCCD-RAW` | images/raw | raf |
| 10 | starts with a UTF-32 or UTF-16 byte-order mark (`FF FE 00 00`, `00 00 FE FF`, `FF FE`, `FE FF`, checked in that order) and decodes as that encoding with no NUL character | text, below | text, below |
| 11 | starts `ID3` and a version byte 2, 3 or 4, or with MPEG audio frames (below) | audio/mp3 | mp3 |
| 12 | starts `fLaC` / `OggS` | audio/flac / audio/ogg | flac / ogg |
| 13 | starts `1A 45 DF A3` (EBML) | video/webm when `webm` occurs in the first 64 bytes, else video/mkv | webm / mkv |
| 14 | a zip: starts `PK\3\4` or `PK\5\6` | see below | see below |
| 15 | starts `1F 8B` (gzip) | archives/gz | `tar.gz` when the name ends `.tar.gz` or `.tgz` (any case), else gz |
| 16 | `ustar` at offset 257 | archives/tar | tar |
| 17 | starts `37 7A BC AF 27 1C` | archives/7z | 7z |
| 18 | starts `Rar!\x1a\x07` | archives/rar | rar |
| 19 | UTF-8 text: an optional UTF-8 BOM, then valid UTF-8 with no NUL character | text, below | text, below |
| 20 | legacy text: the normalized claimed extension is a text extension, there is no NUL byte, the bytes decode as Windows-1252 (cp1252; the undefined bytes `81 8D 8F 90 9D` fail) and the result has no control character other than tab, line feed, form feed and carriage return | the group of that text extension | that extension |
| 21 | MPEG transport stream: at least 3 × 188 bytes, and byte `47` at every multiple of 188 within the first 20 packets the file holds | video/ts | ts |
| 22 | anything else | other/`<ext>` for a claimed extension that is not a text extension and not in the table's list below; else other/bin | that extension, else bin |

- **The table's extensions** (never kept as other/`<ext>`): `pdf png jpg gif webp wav avi heic avif mov
  m4a cr3 mp4 tiff raf mp3 flac ogg webm mkv zip gz tar 7z rar ts epub odt ods odp`, every Office
  extension below, and the aliases `jpeg jpe jfif tif`. The raw extensions are not in this list, so a
  raw file that is not TIFF-shaped keeps its extension as other/`<raw>`; a claimed `bin` is kept as
  other/bin.
- **ISO media brands**: the major brand is bytes 8-11; the compatible brands are the 4-byte groups
  after the minor version (bytes 16 on), up to the end of the `ftyp` box. In this order: major brand
  `avif` or `avis`, or major brand `mif1` or `msf1` with `avif` or `avis` among the compatible brands →
  images/avif `avif`; major brand among `heic heix hevc hevx heim heis mif1 msf1` → images/heic
  `heic`; major brand `qt  ` → video/mov `mov`; major brand `M4A ` or `M4B ` → audio/m4a `m4a`; major
  brand `crx ` → images/raw `cr3`; anything else → video/mp4 `mp4`.
- **Raw extensions**: `dng nef cr2 arw orf rw2 pef srw nrw 3fr erf kdc mos mef iiq`.
- **MPEG audio frames**: a frame header is 4 bytes: byte 0 `FF`; in byte 1 the top 3 bits set, the
  version bits (4-3: `11` MPEG-1, `10` MPEG-2, `00` MPEG-2.5) not `01` and the layer bits (2-1: `11`
  Layer I, `10` Layer II, `01` Layer III) not `00`; in byte 2 the bitrate index (bits 7-4) neither 0
  nor 15, the sample-rate index (bits 3-2) not 3, and the padding bit (bit 1). Bitrates in kbit/s for
  indexes 1 to 14: MPEG-1 Layer I `32 64 96 128 160 192 224 256 288 320 352 384 416 448`, Layer II
  `32 48 56 64 80 96 112 128 160 192 224 256 320 384`, Layer III `32 40 48 56 64 80 96 112 128 160 192
  224 256 320`; MPEG-2 and 2.5 Layer I `32 48 56 64 80 96 112 128 144 160 176 192 224 256`, Layers II
  and III `8 16 24 32 40 48 56 64 80 96 112 128 144 160`. Sample rates in Hz for indexes 0 to 2:
  MPEG-1 `44100 48000 32000`, MPEG-2 `22050 24000 16000`, MPEG-2.5 `11025 12000 8000`. A frame's
  length in bytes, with the bitrate in bit/s and each division rounded down: Layer I
  `(12 × bitrate / rate + padding) × 4`; Layer II, and Layer III of MPEG-1, `144 × bitrate / rate +
  padding`; Layer III of MPEG-2 and 2.5, `72 × bitrate / rate + padding`. The file matches when it
  starts with a frame header and, if it holds at least that frame's length plus 4 bytes, a second
  header with the same version and layer starts right after the first frame.
- **Zips** are read from their end-of-central-directory record: the last `PK\5\6` in the final 65,557
  bytes whose comment length (bytes 20-21 of the record) reaches exactly the end of the file, of the
  last 16 `PK\5\6` there. Its central directory spans from the offset the record gives (bytes 16-19,
  counted from the start of the file) to the record. A name is looked up in that span: the entry
  named N is the first place in it where a central-directory header (`PK\1\2` and 42 more bytes,
  whose name-length field, bytes 28-29, holds N's length in bytes) is followed by N; its flags, method,
  packed size and local header's offset are the header's (bytes 8-9, 10-11, 20-23, 42-45). A zip
  without such a record, whose record gives the offset `FFFFFFFF` (ZIP64), or whose offset lies past
  the record, has no names.
  - **Office**: a zip holding `word/document.xml` is Word, `xl/workbook.xml` or
    `xl/workbook.bin` Excel, `ppt/presentation.xml` PowerPoint (checked in that order). The content
    type of that main part (the `Override` for its part name in `[Content_Types].xml`, part names
    compared ignoring case, else the `Default` for its file extension; the first such element of
    `[Content_Types].xml`, read as UTF-8) picks the extension:
    Word `docx docm dotx dotm`, Excel `xlsx xlsm xltx xltm xlam xlsb`, PowerPoint `pptx pptm potx potm
    ppsx ppsm ppam`, by the standard content types (`…wordprocessingml.document.main+xml` → docx,
    `…ms-word.document.macroEnabled.main+xml` → docm, `…wordprocessingml.template.main+xml` → dotx,
    `…ms-word.template.macroEnabledTemplate.main+xml` → dotm; `…spreadsheetml.sheet.main+xml` → xlsx,
    `…ms-excel.sheet.macroEnabled.main+xml` → xlsm, `…spreadsheetml.template.main+xml` → xltx,
    `…ms-excel.template.macroEnabled.main+xml` → xltm, `…ms-excel.addin.macroEnabled.main+xml` → xlam,
    `…ms-excel.sheet.binary.macroEnabled.main` → xlsb; `…presentationml.presentation.main+xml` → pptx,
    `…ms-powerpoint.presentation.macroEnabled.main+xml` → pptm, `…presentationml.template.main+xml` →
    potx, `…ms-powerpoint.template.macroEnabled.main+xml` → potm, `…presentationml.slideshow.main+xml`
    → ppsx, `…ms-powerpoint.slideshow.macroEnabled.main+xml` → ppsm,
    `…ms-powerpoint.addin.macroEnabled.main+xml` → ppam; compared ignoring case). When the content
    type is missing or none of these, a claimed extension of the same family decides, else the plain
    docx, xlsx or pptx. The groups are documents, spreadsheets and presentations; the type is the
    extension.
  - Otherwise an entry named `mimetype` whose content is `application/vnd.oasis.opendocument.text` →
    documents/odt, `…opendocument.spreadsheet` → spreadsheets/ods, `…opendocument.presentation` →
    presentations/odp, `application/epub+zip` → documents/epub.
  - Any other zip keeps a claimed extension that is not a text extension and not in the table's list,
    as other/`<ext>` (`.jar`, `.pages`, `.apk`, `.whl`); otherwise it is archives/zip `zip`.
- **Text** (rows 10, 19, 20) is decided on `text`, the decoded text without any BOM:
  1. a normalized claimed extension in the text list keeps its group; the type is the extension:
     - documents: `txt md rst tex org rtf html`; images: `svg`; spreadsheets: `csv tsv`;
     - data: `json jsonl geojson ipynb xml yaml toml ini cfg conf sql log srt vtt ics vcf bib`;
     - code: `py js mjs cjs ts tsx jsx c h cc cpp hpp cs java kt go rs rb php swift scala lua pl r sh
       bash zsh fish ps1 bat css scss less vue svelte dart proto`;
  2. any other claimed extension that is not in the table's list is kept: other/`<ext>` (`.gpx`,
     `.kml`, `.plist`, `.url`);
  3. otherwise (no claimed extension, or one in the table's list) the content decides, the first match
     winning. `head` is `text` without leading whitespace; `first` is the first line of `text`; lines
     are split at `\n` with a trailing `\r` dropped. `head` starts `<svg`, or starts `<?xml` and, after
     the first `?>` within its first 4,096 characters and optional space, `<svg` → images/svg; `head`
     starts `<!doctype html` or `<html`, ignoring case → documents/html; `head` starts `{\rtf` →
     documents/rtf; `head` starts `{` or `[`, no array or object is nested more than 512 deep, and
     `text` is JSON by RFC 8259 (so `NaN` and `Infinity` are not JSON) → data/json; `first` starts `# `
     or is `---` → documents/md; among the first 1,000 lines, at least 3 non-blank ones (a blank line
     holds only whitespace), all with the same number of commas, at least one → spreadsheets/csv;
     `first` starts
     `YYYY-MM-DD HH:MM:SS` or `YYYY-MM-DDTHH:MM:SS` (digits, not checked as a date) → data/log;
     otherwise documents/txt. So a text file without an extension (`Makefile`) is txt.

## 3. Date: embedded, then the name, else undated

A file's date is the first of these that gives a real calendar date:

1. **Embedded**, with a year from 1971 to 2099, taken as stored (no time-zone conversion):

   | Type | Where |
   |---|---|
   | jpg | the first APP1 segment that starts `Exif\0\0`, before the image data: TIFF → IFD0's tag `8769` → the Exif IFD's DateTimeOriginal (tag `9003`, ASCII, `YYYY:MM:DD …`) |
   | tiff, raw that is TIFF | the file itself as TIFF → IFD0's tag `8769` → Exif IFD → tag `9003` |
   | heic, avif | the first item of type `Exif` (the top-level `meta` box → its first `iinf` → its first `iloc` extents, in the file or in its first `idat`): its first 4 bytes say how many bytes after them the TIFF starts (a leading `Exif\0\0` there is skipped) → Exif IFD → tag `9003` |
   | cr3 | the first top-level `moov` box → its first Canon `uuid` box (`85c0b687-820f-11e0-8111-f4ce462b6a48`) → its first `CMT2` box, a TIFF whose first IFD holds tag `9003`; when that gives no real date, its first `CMT1` box as TIFF → Exif IFD → tag `9003` |
   | webp | the `EXIF` chunk (a leading `Exif\0\0` is skipped) → Exif IFD → tag `9003` |
   | png | the first `eXIf` chunk (a leading `Exif\0\0` is skipped) → Exif IFD → tag `9003`; else the first `tEXt` chunk with the keyword `Creation Time` decides: the first 64 bytes of its text (Latin-1), after optional space, start `YYYY-MM-DD`, or else three ASCII letters and a comma and optional space (optional), a 1- or 2-digit day, space, three ASCII letters naming an English month (`Jan` … `Dec`, any case), space, a 4-digit year |
   | pdf | the document information dictionary: the last `/Info N G R` in the file names object `N G`; when that object is written out plainly (the last `N G obj` … `endobj` in the file), its `/CreationDate (` literal decides, or there is no PDF date. When there is no `/Info` reference or the object is not written out plainly (inside a compressed object stream), the last `/CreationDate (` literal anywhere in the file decides. A literal's value is the text up to the next `)` (at most 64 bytes), read as `D:YYYYMMDD…` or `YYYYMMDD…` |
   | docx, docm, dotx, dotm, xlsx, xlsm, xltx, xltm, xlam, xlsb, pptx, pptm, potx, potm, ppsx, ppsm, ppam | the zip entry `docProps/core.xml`: the text of the first element written `dcterms:created`, after optional space, starting `YYYY-MM-DD` |
   | odt, ods, odp | the zip entry `meta.xml`: the text of the first element written `meta:creation-date`, after optional space, starting `YYYY-MM-DD` |
   | mp4, mov, m4a | the first top-level `moov` box, the first `mvhd` box in it: its creation time, seconds since 1904-01-01 UTC (0 means none) |
   | md | front matter, read from the first 1,000 lines of `text`: when the first line is exactly `---`, the first line that starts `date:` before a line that is `---` once trimmed of spaces and tabs at both ends (a closing line is not required); its value, trimmed of spaces and tabs and then of `'` and `"`, starting `YYYY-MM-DD` |

2. **The name**: a name in scheme form (§4) gives its date part (a year from 1971 to 2099); any other
   name gives the first real date among the `YYYY?MM?DD` in the name without its extension, where `?`
   is the same one of `-`, `_`, `.` or nothing in both places, not touching other digits, with a year
   from 1990 to 2039 (a candidate that is not a real date in range is skipped).
3. Otherwise the file is **undated**.

**Malformed files.** Every structure above is read with bounds checks. A structure that is truncated,
points outside the file, or is inconsistent gives no date, and nothing else: a JPEG segment or PNG
chunk that runs past the end of the file is not read; an IFD at an offset under 8, with more than
1,024 entries, or whose entries run past the end, is not read; a DateTimeOriginal longer than 64
bytes or running past the end is not read; an ISO box whose size is under its header (8 bytes, or 16
with a 64-bit size) or runs past its parent stops the walk of that parent (size 0 runs to the end of
the parent); a zip entry that is encrypted, uses a method other than stored or deflate, has no
`PK\3\4` header at its offset, whose data runs past the end of the file, or whose data is not valid
DEFLATE as far as it is read (by the rules of RFC 1951 as puff.c checks them: no over-subscribed
code, an incomplete code only as a single code of length 1, a complete code-length code), is not
read. A file is never refused for its content.

**Reading limits.** Every structure is read only so far, so a folder at the limits of §1 is checked in
bounded time; what lies beyond is not read, and a date there is not found:

| What | Read as far as |
|---|---|
| a zip part (`[Content_Types].xml`, `docProps/core.xml`, `meta.xml`, `mimetype`) | its first 4,096 bytes of content, and of a deflated part only its first 4 DEFLATE blocks |
| the zip end record | the last 16 `PK\5\6` in the final 65,557 bytes |
| JPEG | the first 64 markers after SOI (each `FF` fill byte counts as one) |
| PNG, RIFF (WebP) | the first 1,024 chunks |
| ISO media (MP4, MOV, M4A, HEIF, AVIF, CR3) | the first 1,024 boxes of the file and of any one box |
| a TIFF IFD | 1,024 entries (an IFD with more is not read) |
| HEIF `iloc` | its first 1,024 items, holding 1,024 extents in all (the item past that budget, and those after it, are not read) |
| a HEIF Exif item | the first 1 MiB of its extents, in order |
| an `ftyp` box | its first 1,024 compatible brands |
| a PNG `tEXt` date | the first 64 bytes of its text |
| Markdown front matter, the CSV test | the first 1,000 lines |

The raw value pinned with an embedded date is at most its first 64 characters.

Out of scope, giving no embedded date: XMP, PDF dates written in hex or UTF-16, PDF information inside
compressed object streams (the fallback above applies), `zTXt` and `iTXt`, PNG `tIME`, ID3 years,
QuickTime `©day`, EPUB dates, HTML meta dates, ZIP64, the dates of RW2, ORF, RAF and other raw files
that are not TIFF-shaped or CR3, and text in any legacy encoding other than Windows-1252.

## 4. Name and place

- **Scheme form**: `<date>_<slug>[_<n>].<ext>`, where `<date>` is `YYYY-MM-DD` or `undated`, `<slug>`
  is lowercase letters and digits in hyphen-joined words, `<n>` is 2 or more without a leading zero,
  and `<ext>` is `tar.gz` or 1 to 10 lowercase letters and digits. A name in scheme form keeps its
  slug, so organizing an organized folder changes nothing.
- **Slug** of any other name, from the name without its extension (without `.tar.gz` or `.tgz` for a
  `tar.gz`), in this order:
  1. remove the real date §3 step 2 reads from the name (a skipped candidate stays), whether or not
     the file's date came from it;
  2. Unicode NFKD, keeping ASCII characters only; then lowercase;
  3. strip a leading `copy of `, repeatedly;
  4. strip from the end, repeatedly until none is left, any of: optional space, `(`, digits, `)`;
     space, `-`, space, `copy`, optionally followed by space, `(`, digits, `)`; space and `copy`,
     optionally followed by space and digits; `_` or `-`, then `copy`, then optional digits;
  5. turn every run of characters other than `a-z0-9` into one `-` and trim `-` from both ends;
  6. keep at most 60 characters and trim a trailing `-`; an empty slug is `file`.
- A name has a **copy marker** when it is not in scheme form and step 3 or step 4 strips something.
- A name **names its type** when it ends, ignoring case, with `.` and the extension the rules give it,
  or with `.` and an alias of it (`jpeg`, `jpe`, `jfif` for jpg; `tif` for tiff; `markdown` for md;
  `yml` for yaml; `htm` for html; `ndjson` for jsonl; `tgz` for tar.gz).
- **Base path**: `organized/<group>/<type>/<YYYY>/<YYYY-MM-DD>_<slug>.<ext>`, or
  `organized/<group>/<type>/undated/undated_<slug>.<ext>` for an undated file.
- A file **conforms** when it sits at its base path, or at its base path with `_<n>` (n ≥ 2) before
  the extension. Junk and empty files never conform.

## 5. The plan

- **Order**: conforming files first; then names without a copy marker before names with one; then names
  that name their type before others; then fewer folders in the path before more; then the path,
  comparing characters by code point. A file's number `i` is its place in this order, from 0.
- When the run starts, every path in the folder is **taken**, except hidden entries and the empty
  folders the run removes first (below). Walk the files in order:
  1. junk → **delete** (junk);
  2. an empty file → **delete** (empty);
  3. the same bytes (sha256) as an earlier file that is kept → **delete** (copy): so the copy kept is
     the first in the order, a conforming one if any, else the one with the most original name;
  4. a conforming file → **stays**;
  5. any other file → **moves** to the first of `base`, `base_2`, `base_3`, … that is not taken
     (comparing paths ignoring letter case and Unicode normalization), and takes it.
- **One run does at most 60 actions** (moves and deletes): the first 60 in the order. The rest wait for
  the next run, where the same rules start again from the folder as it is then.
- **Folders**: a folder inside the folder that is not hidden and holds no file and no hidden entry
  anywhere below it is removed: when the run starts (its first survey) and after every apply call.
  When the run ends, every such folder is gone; the folder itself always stays.
