"""Readers for the file structures the rules look inside, written by hand with bounds checks: zip entries
looked up by name, TIFF/EXIF, JPEG markers, PNG and RIFF chunks, ISO media boxes (HEIF items, Canon CR3
metadata), a PDF's document information and Markdown front matter.

Shared, byte for byte, by src/plugin/ and verifier/. Nothing here raises on a malformed file: a
structure that does not read gives None (or nothing), and the rules then fall back. Every walk stops at
a fixed count (RULES.md §3, "Reading limits"), so a file's cost is bounded whatever it holds: the
verifier re-derives every file's facts twice within its time limit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .inflate import inflate

PART_BYTES = 4096  # a zip part is read as far as its first 4,096 bytes of content
PART_BLOCKS = 4  # and its first 4 DEFLATE blocks
EOCD_SEARCH = 22 + 65535
EOCD_TRIES = 16
JPEG_MARKERS = 64
CHUNKS = 1024
BOXES = 1024
MAX_IFD_ENTRIES = 1024
ILOC_ITEMS = 1024
ILOC_EXTENTS = 1024
ITEM_BYTES = 1 << 20  # a HEIF Exif item is read as far as its first 1 MiB
FRONT_LINES = 1000
TIFF_HEADERS = (b"II*\x00", b"MM\x00*")
EXIF_HEADER = b"Exif\x00\x00"
CANON_UUID = bytes.fromhex("85c0b687820f11e08111f4ce462b6a48")
PDF_LITERAL = 64
PDF_CREATION = re.compile(rb"/CreationDate\s*\(")
# Searched in the reversed file, so the first match is the file's last one.
PDF_INFO_REVERSED = re.compile(rb"R\s+([0-9]+)\s+([0-9]+)\s+ofnI/")
PDF_CREATION_REVERSED = re.compile(rb"\(\s*etaDnoitaerC/")
HEADER = 46  # a central-directory header's fixed part, before the entry's name
# The names the rules look up in a zip. Each is searched for as the name, with a lookbehind for its
# header (PK 1 2, then 42 bytes whose name-length field, at 28, holds the name's length): a search for
# the name itself is fast however many headers or names a crafted directory holds.
ZIP_NAMES = ("word/document.xml", "xl/workbook.xml", "xl/workbook.bin", "ppt/presentation.xml", "[Content_Types].xml", "docProps/core.xml", "mimetype", "meta.xml")


def header_pattern(name: str) -> re.Pattern:
    raw = re.escape(name.encode())
    length = re.escape(len(name.encode()).to_bytes(2, "little"))
    return re.compile(raw + rb"(?<=PK\x01\x02[\x00-\xff]{24}" + length + rb"[\x00-\xff]{16}" + raw + rb")")


ZIP_HEADERS = {name: header_pattern(name) for name in ZIP_NAMES}


def number(data: bytes, start: int, width: int, big: bool) -> int | None:
    """The unsigned integer of `width` bytes at `start`, or None past the end."""
    if start < 0 or start + width > len(data):
        return None
    return int.from_bytes(data[start : start + width], "big" if big else "little")


# ----- Zip -----


@dataclass(frozen=True)
class ZipEntry:
    name: str
    flags: int
    method: int
    packed: int
    offset: int


def end_record(data: bytes) -> int | None:
    """Where the zip's end-of-central-directory record starts: the last `PK\\5\\6` in the final 65,557
    bytes whose comment length reaches exactly the end of the file, trying at most the last 16; None
    when there is none."""
    start = max(0, len(data) - EOCD_SEARCH)
    end = data.rfind(b"PK\x05\x06", start)
    for _try in range(EOCD_TRIES):
        if end < 0:
            return None
        comment = number(data, end + 20, 2, False)
        if comment is not None and end + 22 + comment == len(data):
            return end
        end = data.rfind(b"PK\x05\x06", start, end + 3)
    return None


LAST_DIRECTORY: list = [None, None]  # (the data, its central directory's span): a file is looked up several times


def zip_directory(data: bytes) -> tuple[int, int] | None:
    """The central directory's span: from the offset the end record gives (counted from the start of the
    file) to the end record; None without an end record, or for ZIP64."""
    if LAST_DIRECTORY[0] is data:
        return LAST_DIRECTORY[1]
    end = end_record(data)
    offset = None if end is None else number(data, end + 16, 4, False)
    span = None if end is None or offset is None or offset == 0xFFFFFFFF or offset > end else (offset, end)
    LAST_DIRECTORY[0], LAST_DIRECTORY[1] = data, span
    return span


def zip_entry(data: bytes, name: str) -> ZipEntry | None:
    """The entry named `name`: the first central-directory header in the directory's span that is
    followed by that name and gives its length, or None."""
    span = zip_directory(data)
    if span is None:
        return None
    found = (ZIP_HEADERS.get(name) or header_pattern(name)).search(data, span[0] + HEADER, span[1])
    if found is None:
        return None
    at = found.start() - HEADER
    return ZipEntry(name=name, flags=number(data, at + 8, 2, False), method=number(data, at + 10, 2, False), packed=number(data, at + 20, 4, False), offset=number(data, at + 42, 4, False))


def zip_read(data: bytes, entry: ZipEntry) -> bytes | None:
    """The first PART_BYTES bytes of an entry's content when it is stored or deflated and unencrypted,
    its local header is at its offset and its data lies in the file; else None."""
    if entry.flags & 1 or entry.method not in (0, 8):
        return None
    if data[entry.offset : entry.offset + 4] != b"PK\x03\x04":
        return None
    name_length = number(data, entry.offset + 26, 2, False)
    extra_length = number(data, entry.offset + 28, 2, False)
    if name_length is None or extra_length is None:
        return None
    start = entry.offset + 30 + name_length + extra_length
    if start + entry.packed > len(data):
        return None
    if entry.method == 0:
        return data[start : start + min(entry.packed, PART_BYTES)]
    return inflate(data, PART_BYTES, PART_BLOCKS, start, start + entry.packed)


def zip_member(data: bytes, name: str) -> bytes | None:
    """The start of the content of the entry named `name`, as zip_read gives it, or None."""
    entry = zip_entry(data, name)
    return None if entry is None else zip_read(data, entry)


# ----- TIFF and EXIF -----


def ifd_find(tiff: bytes, ifd: int, big: bool, tag: int, kind: int | None) -> tuple[int, int] | None:
    """The first entry of the IFD at `ifd` with `tag` (and type `kind`): (count, value position); None
    when there is none or the IFD does not read (an offset under 8, over 1,024 entries, past the end)."""
    count = number(tiff, ifd, 2, big)
    if count is None or ifd < 8 or count > MAX_IFD_ENTRIES or ifd + 2 + 12 * count > len(tiff):
        return None
    order = "big" if big else "little"
    for at in range(ifd + 2, ifd + 2 + 12 * count, 12):
        if int.from_bytes(tiff[at : at + 2], order) == tag and (kind is None or int.from_bytes(tiff[at + 2 : at + 4], order) == kind):
            return int.from_bytes(tiff[at + 4 : at + 8], order), at + 8
    return None


def ifd_date(tiff: bytes, ifd: int, big: bool) -> str | None:
    """The DateTimeOriginal (tag 9003, ASCII, at most 64 bytes) in the IFD at `ifd`, as stored, or None."""
    found = ifd_find(tiff, ifd, big, 0x9003, 2)
    if found is None:
        return None
    items, at = found
    start = at if items <= 4 else number(tiff, at, 4, big)
    if start is None or items > 64 or start + items > len(tiff):
        return None
    return tiff[start : start + items].split(b"\x00", 1)[0].decode("latin-1")


def first_ifd(tiff: bytes) -> tuple[int, bool] | None:
    """A TIFF structure's first IFD offset and byte order (True for big-endian), or None."""
    if tiff[:4] not in TIFF_HEADERS:
        return None
    big = tiff[:2] == b"MM"
    first = number(tiff, 4, 4, big)
    return None if first is None else (first, big)


def tiff_date_original(tiff: bytes) -> str | None:
    """A TIFF structure's DateTimeOriginal: IFD0 -> its Exif IFD (tag 8769) -> tag 9003, or None."""
    found = first_ifd(tiff)
    if found is None:
        return None
    first, big = found
    pointer = ifd_find(tiff, first, big, 0x8769, None)
    if pointer is None:
        return None
    exif = number(tiff, pointer[1], 4, big)
    return None if exif is None else ifd_date(tiff, exif, big)


def first_ifd_date(tiff: bytes) -> str | None:
    """Tag 9003 in a TIFF structure's first IFD (a CR3 CMT2 box is the Exif IFD itself), or None."""
    found = first_ifd(tiff)
    return None if found is None else ifd_date(tiff, found[0], found[1])


def jpeg_exif(data: bytes) -> bytes | None:
    """The TIFF inside a JPEG's first APP1 `Exif\\0\\0` segment, among its first 64 markers (fill bytes
    count), or None."""
    at = 2
    for _marker in range(JPEG_MARKERS):
        if at + 4 > len(data) or data[at] != 0xFF:
            return None
        marker = data[at + 1]
        if marker == 0xFF:
            at += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            at += 2
            continue
        if marker in (0xDA, 0xD9):
            return None
        length = number(data, at + 2, 2, True)
        if length is None or length < 2 or at + 2 + length > len(data):
            return None
        if marker == 0xE1 and data.startswith(EXIF_HEADER, at + 4, at + 2 + length):
            return data[at + 4 + len(EXIF_HEADER) : at + 2 + length]
        at += 2 + length
    return None


# ----- PNG and RIFF chunks -----


def png_chunks(data: bytes) -> list[tuple[bytes, int, int]]:
    """A PNG's first 1,024 chunks up to IEND, as (kind, body start, body end), stopping where the file
    stops reading."""
    chunks = []
    at = 8
    for _chunk in range(CHUNKS):
        length = number(data, at, 4, True)
        if length is None or at + 12 + length > len(data):
            break
        kind = data[at + 4 : at + 8]
        chunks.append((kind, at + 8, at + 8 + length))
        if kind == b"IEND":
            break
        at += 12 + length
    return chunks


def riff_chunks(data: bytes) -> list[tuple[bytes, int, int]]:
    """A RIFF file's first 1,024 top-level chunks after its form type, as (fourcc, body start, body end)."""
    chunks = []
    at = 12
    for _chunk in range(CHUNKS):
        size = number(data, at + 4, 4, False)
        if size is None or at + 8 + size > len(data):
            break
        chunks.append((data[at : at + 4], at + 8, at + 8 + size))
        at += 8 + size + (size & 1)
    return chunks


# ----- ISO media boxes -----


def boxes(data: bytes, start: int, end: int) -> list[tuple[bytes, int, int]]:
    """The first 1,024 (type, body start, body end) boxes between `start` and `end`."""
    found = []
    at = start
    for _box in range(BOXES):
        if at + 8 > end:
            break
        size = number(data, at, 4, True)
        kind = data[at + 4 : at + 8]
        header = 8
        if size == 1:
            size = number(data, at + 8, 8, True)
            header = 16
        elif size == 0:
            size = end - at
        if size is None or size < header or at + size > end:
            break
        found.append((kind, at + header, at + size))
        at += size
    return found


class Unreadable(ValueError):
    """A structure that does not read: the caller gives no date."""


def need(value: int | None) -> int:
    if value is None:
        raise Unreadable("past the end")
    return value


def item_location(data: bytes, start: int, end: int, wanted: int) -> tuple[int, int, list[tuple[int, int]]] | None:
    """Where an `iloc` box puts item `wanted`: (construction method, base offset, [(extent offset, extent
    length)]), reading its items in order, at most 1,024 items and 1,024 extents in all; None when it is
    not among them."""
    version = data[start]
    offset_size, length_size = data[start + 4] >> 4, data[start + 4] & 15
    base_size, index_size = data[start + 5] >> 4, (data[start + 5] & 15 if version in (1, 2) else 0)
    id_width = 2 if version < 2 else 4
    at = start + 6
    count = need(number(data, at, id_width, True))
    at += id_width
    budget = ILOC_EXTENTS
    for _index in range(min(count, ILOC_ITEMS)):
        item = need(number(data, at, id_width, True))
        at += id_width
        method = 0
        if version in (1, 2):
            method = need(number(data, at, 2, True)) & 15
            at += 2
        at += 2  # data_reference_index
        base = need(number(data, at, base_size, True)) if base_size else 0
        at += base_size
        extents = need(number(data, at, 2, True))
        at += 2
        if extents > budget:
            return None
        budget -= extents
        spans = []
        for _extent in range(extents):
            at += index_size
            offset = need(number(data, at, offset_size, True)) if offset_size else 0
            at += offset_size
            length = need(number(data, at, length_size, True)) if length_size else 0
            at += length_size
            spans.append((offset, length))
        if at > end:
            raise Unreadable("iloc runs past its box")
        if item == wanted:
            return method, base, spans
    return None


def exif_item_ids(data: bytes, start: int, end: int) -> list[int]:
    """The ids of an `iinf` box's items of type `Exif`, in order, among its first 1,024 boxes."""
    version = data[start]
    width = 2 if version == 0 else 4
    ids = []
    for kind, body, body_end in boxes(data, start + 4 + width, end):
        if kind != b"infe" or body >= body_end or data[body] < 2:
            continue
        id_width = 2 if data[body] == 2 else 4
        item = need(number(data, body + 4, id_width, True))
        if data[body + 4 + id_width + 2 : body + 4 + id_width + 6] == b"Exif":
            ids.append(item)
    return ids


def heif_exif(data: bytes) -> bytes | None:
    """The TIFF of a HEIF/AVIF file's first `Exif` item (meta -> iinf -> iloc, in the file or in idat):
    the item's first 4 bytes give how far past them the TIFF header starts."""
    try:
        for kind, start, end in boxes(data, 0, len(data)):
            if kind != b"meta":
                continue
            ids, iloc, idat = [], None, None
            for inner, body, body_end in boxes(data, start + 4, end):
                if inner == b"iinf" and not ids:
                    ids = exif_item_ids(data, body, body_end) or [None]
                elif inner == b"iloc" and iloc is None:
                    iloc = (body, body_end)
                elif inner == b"idat" and idat is None:
                    idat = body
            if not ids or ids[0] is None or iloc is None:
                return None
            location = item_location(data, iloc[0], iloc[1], ids[0])
            if location is None:
                return None
            method, base, spans = location
            if method not in (0, 1) or (method == 1 and idat is None):
                return None
            origin = base + (idat if method == 1 else 0)
            pieces: list[bytes] = []
            held = 0
            for offset, length in spans:
                start = origin + offset
                stop = start + length if length else len(data)
                piece = data[start : min(stop, start + ITEM_BYTES - held)]
                pieces.append(piece)
                held += len(piece)
                if held >= ITEM_BYTES:
                    break
            payload = b"".join(pieces)
            skip = need(number(payload, 0, 4, True))
            tiff = payload[4 + skip :]
            tiff = tiff.removeprefix(EXIF_HEADER)  # some writers leave the marker in
            return tiff if tiff[:4] in TIFF_HEADERS else None
    except (Unreadable, IndexError):
        return None
    return None


def cr3_dates_original(data: bytes) -> list[str]:
    """A CR3's DateTimeOriginal values, in the order the rules try them: the first top-level `moov` ->
    its Canon `uuid` box -> `CMT2` (the Exif IFD as a TIFF) tag 9003, then `CMT1` (IFD0 as a TIFF) ->
    Exif IFD -> tag 9003."""
    for kind, start, end in boxes(data, 0, len(data)):
        if kind != b"moov":
            continue
        for inner, body, body_end in boxes(data, start, end):
            if inner != b"uuid" or data[body : body + 16] != CANON_UUID:
                continue
            found = {name: data[part:part_end] for name, part, part_end in reversed(boxes(data, body + 16, body_end))}
            values = [first_ifd_date(found[b"CMT2"]) if b"CMT2" in found else None, tiff_date_original(found[b"CMT1"]) if b"CMT1" in found else None]
            return [value for value in values if value is not None]
        return []
    return []


def mvhd_seconds(data: bytes) -> int | None:
    """The `moov`/`mvhd` creation time, seconds since 1904-01-01 UTC; None when absent or 0."""
    for kind, start, end in boxes(data, 0, len(data)):
        if kind != b"moov":
            continue
        for inner, body, body_end in boxes(data, start, end):
            if inner != b"mvhd" or body >= body_end:
                continue
            version = data[body]
            seconds = number(data, body + 4, 8 if version == 1 else 4, True)
            if seconds is None or body + 4 + (8 if version == 1 else 4) > body_end:
                return None
            return seconds or None
        return None
    return None


# ----- PDF and Markdown -----


def literal(data: bytes, end: int) -> str:
    """A PDF literal's text after the `(` that ends at `end`: up to the next `)`, at most 64 bytes."""
    return data[end : end + PDF_LITERAL].split(b")", 1)[0].decode("latin-1")


def pdf_creation(data: bytes) -> str | None:
    """The CreationDate of a PDF's document information dictionary: the object the last `/Info N G R`
    names, when it is written out plainly (the last `N G obj` ... `endobj`), decides; without an `/Info`
    reference, or when that object is not written out plainly, the last `/CreationDate (` literal in
    the file. None when the deciding place holds no CreationDate literal. Each "last" is found by one
    search of the reversed file."""
    backwards = data[::-1]
    size = len(data)
    info = PDF_INFO_REVERSED.search(backwards)
    if info is not None:
        # `N G obj`, reversed: the generation's and the number's digits come reversed from the search
        header = re.compile(rb"\bjbo\s+" + info.group(1) + rb"\s+" + info.group(2) + rb"(?![0-9])")
        body = header.search(backwards)
        if body is not None:
            after = size - body.start()  # where `obj` ends in the file
            close = data.find(b"endobj", after)
            if close >= 0:
                found = PDF_CREATION.search(data, after, close)
                return literal(data, found.end()) if found else None
    last = PDF_CREATION_REVERSED.search(backwards)
    return literal(data, size - last.start()) if last else None


def front_matter_date(text: str) -> str | None:
    """The value of the first `date:` line in a leading `---` front matter, read from the first 1,000
    lines; trimmed of spaces and tabs, then of quotes. None when there is none."""
    lines = text.split("\n", FRONT_LINES)[:FRONT_LINES]
    if lines[0].removesuffix("\r") != "---":
        return None
    for line in lines[1:]:
        line = line.removesuffix("\r")
        if line.strip(" \t") == "---":
            return None
        if line.startswith("date:"):
            return line[5:].strip(" \t").strip("'\"")
    return None
