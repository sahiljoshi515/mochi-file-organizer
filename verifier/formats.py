"""Readers for the file structures the rules look inside, written by hand with bounds checks: a zip's
central directory and entries, TIFF/EXIF, JPEG segments, PNG and RIFF chunks, ISO media boxes, PDF
CreationDate literals and Markdown front matter.

Shared, byte for byte, by src/plugin/ and verifier/. Nothing here raises on a malformed file: a
structure that does not read gives None (or nothing), and the rules then fall back.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .inflate import inflate

ENTRY_LIMIT = 1 << 20  # the most a zip entry the rules read may hold, packed or unpacked
MAX_ENTRIES = 65535
MAX_IFD_ENTRIES = 1024
TIFF_HEADERS = (b"II*\x00", b"MM\x00*")
EXIF_HEADER = b"Exif\x00\x00"
EXIF_SEARCH = 4 << 20
PDF_CREATION = re.compile(rb"/CreationDate\s*\(")
FRONT_DATE = re.compile(r"date:[ \t]*(.*?)[ \t]*$")


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
    size: int
    offset: int


def zip_entries(data: bytes) -> list[ZipEntry]:
    """The entries of a zip's central directory, in order; [] when there is no readable one (or ZIP64)."""
    end = data.rfind(b"PK\x05\x06", max(0, len(data) - 22 - 65535))
    if end < 0:
        return []
    count = number(data, end + 10, 2, False)
    offset = number(data, end + 16, 4, False)
    if count is None or offset is None or offset == 0xFFFFFFFF:
        return []
    entries: list[ZipEntry] = []
    for _index in range(min(count, MAX_ENTRIES)):
        if data[offset : offset + 4] != b"PK\x01\x02":
            break
        fields = [number(data, offset + at, width, False) for at, width in ((8, 2), (10, 2), (20, 4), (24, 4), (28, 2), (30, 2), (32, 2), (42, 4))]
        if None in fields:
            break
        flags, method, packed, size, name_length, extra_length, comment_length, local = fields
        name = data[offset + 46 : offset + 46 + name_length].decode("utf-8", "replace")
        entries.append(ZipEntry(name=name, flags=flags, method=method, packed=packed, size=size, offset=local))
        offset += 46 + name_length + extra_length + comment_length
    return entries


def zip_read(data: bytes, entry: ZipEntry) -> bytes | None:
    """An entry's content when it is stored or deflated, unencrypted and at most ENTRY_LIMIT bytes; else None."""
    if entry.flags & 1 or entry.method not in (0, 8) or entry.packed > ENTRY_LIMIT or entry.size > ENTRY_LIMIT:
        return None
    if data[entry.offset : entry.offset + 4] != b"PK\x03\x04":
        return None
    name_length = number(data, entry.offset + 26, 2, False)
    extra_length = number(data, entry.offset + 28, 2, False)
    if name_length is None or extra_length is None:
        return None
    start = entry.offset + 30 + name_length + extra_length
    packed = data[start : start + entry.packed]
    if len(packed) != entry.packed:
        return None
    return packed if entry.method == 0 else inflate(packed, ENTRY_LIMIT)


def zip_member(data: bytes, name: str) -> bytes | None:
    """The content of the first entry named `name`, as zip_read gives it, or None."""
    for entry in zip_entries(data):
        if entry.name == name:
            return zip_read(data, entry)
    return None


# ----- TIFF and EXIF -----


def ifd_entries(tiff: bytes, ifd: int, big: bool) -> list[tuple[int, int, int, int]]:
    """An IFD's (tag, type, count, value position) entries; [] when the IFD does not read."""
    count = number(tiff, ifd, 2, big)
    if count is None or ifd < 8 or count > MAX_IFD_ENTRIES or ifd + 2 + 12 * count > len(tiff):
        return []
    found = []
    for index in range(count):
        at = ifd + 2 + 12 * index
        tag, kind, items = number(tiff, at, 2, big), number(tiff, at + 2, 2, big), number(tiff, at + 4, 4, big)
        found.append((tag, kind, items, at + 8))
    return found


def tiff_date_original(tiff: bytes) -> str | None:
    """A TIFF structure's DateTimeOriginal (Exif IFD 8769, tag 9003, ASCII) as stored, or None."""
    if tiff[:4] not in TIFF_HEADERS:
        return None
    big = tiff[:2] == b"MM"
    first = number(tiff, 4, 4, big)
    if first is None:
        return None
    exif = None
    for tag, _kind, _items, at in ifd_entries(tiff, first, big):
        if tag == 0x8769:
            exif = number(tiff, at, 4, big)
            break
    if exif is None:
        return None
    for tag, kind, items, at in ifd_entries(tiff, exif, big):
        if tag == 0x9003 and kind == 2:
            start = at if items <= 4 else number(tiff, at, 4, big)
            if start is None or items > 64 or start + items > len(tiff):
                return None
            return tiff[start : start + items].split(b"\x00", 1)[0].decode("latin-1")
    return None


def jpeg_exif(data: bytes) -> bytes | None:
    """The TIFF inside a JPEG's first APP1 `Exif\\0\\0` segment, or None."""
    at = 2
    while at + 4 <= len(data):
        if data[at] != 0xFF:
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
        if length is None or length < 2:
            return None
        segment = data[at + 4 : at + 2 + length]
        if marker == 0xE1 and segment.startswith(EXIF_HEADER):
            return segment[len(EXIF_HEADER) :]
        at += 2 + length
    return None


def searched_exif(data: bytes) -> bytes | None:
    """The TIFF after the first `Exif\\0\\0` that is followed by a TIFF header, within the first 4 MiB."""
    at = data.find(EXIF_HEADER, 0, EXIF_SEARCH)
    while 0 <= at < EXIF_SEARCH:
        start = at + len(EXIF_HEADER)
        if data[start : start + 4] in TIFF_HEADERS:
            return data[start:]
        at = data.find(EXIF_HEADER, at + 1, EXIF_SEARCH)
    return None


# ----- PNG and RIFF chunks -----


def png_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    """A PNG's (kind, body) chunks up to IEND, stopping where the file stops reading."""
    chunks = []
    at = 8
    while at + 8 <= len(data):
        length = number(data, at, 4, True)
        kind = data[at + 4 : at + 8]
        if length is None or at + 12 + length > len(data):
            break
        chunks.append((kind, data[at + 8 : at + 8 + length]))
        if kind == b"IEND":
            break
        at += 12 + length
    return chunks


def riff_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    """A RIFF file's top-level (fourcc, body) chunks after its form type."""
    chunks = []
    at = 12
    while at + 8 <= len(data):
        size = number(data, at + 4, 4, False)
        if size is None or at + 8 + size > len(data):
            break
        chunks.append((data[at : at + 4], data[at + 8 : at + 8 + size]))
        at += 8 + size + (size & 1)
    return chunks


# ----- ISO media boxes -----


def boxes(data: bytes, start: int, end: int) -> list[tuple[bytes, int, int]]:
    """The (type, body start, body end) boxes between `start` and `end`."""
    found = []
    at = start
    while at + 8 <= end:
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


def item_locations(data: bytes, start: int, end: int) -> dict[int, tuple[int, int, list[tuple[int, int]]]]:
    """An `iloc` box's items: id -> (construction method, base offset, [(extent offset, extent length)])."""
    version = data[start]
    offset_size, length_size = data[start + 4] >> 4, data[start + 4] & 15
    base_size, index_size = data[start + 5] >> 4, (data[start + 5] & 15 if version in (1, 2) else 0)
    id_width = 2 if version < 2 else 4
    at = start + 6
    count = need(number(data, at, id_width, True))
    at += id_width
    items = {}
    for _index in range(min(count, MAX_IFD_ENTRIES)):
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
        spans = []
        for _extent in range(min(extents, 64)):
            at += index_size
            offset = need(number(data, at, offset_size, True)) if offset_size else 0
            at += offset_size
            length = need(number(data, at, length_size, True)) if length_size else 0
            at += length_size
            spans.append((offset, length))
        if at > end:
            raise Unreadable("iloc runs past its box")
        items[item] = (method, base, spans)
    return items


def exif_item_ids(data: bytes, start: int, end: int) -> list[int]:
    """The ids of an `iinf` box's items of type `Exif`, in order."""
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
            ids, locations, idat = [], {}, None
            for inner, body, body_end in boxes(data, start + 4, end):
                if inner == b"iinf":
                    ids = exif_item_ids(data, body, body_end)
                elif inner == b"iloc":
                    locations = item_locations(data, body, body_end)
                elif inner == b"idat":
                    idat = body
            if not ids or ids[0] not in locations:
                return None
            method, base, spans = locations[ids[0]]
            if method not in (0, 1) or (method == 1 and idat is None):
                return None
            origin = base + (idat if method == 1 else 0)
            payload = b"".join(data[origin + offset : (origin + offset + length) if length else len(data)] for offset, length in spans)
            skip = need(number(payload, 0, 4, True))
            tiff = payload[4 + skip :]
            tiff = tiff.removeprefix(EXIF_HEADER)  # some writers leave the marker in
            return tiff if tiff[:4] in TIFF_HEADERS else None
    except (Unreadable, IndexError):
        return None
    return None


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


def pdf_creation(data: bytes) -> str | None:
    """The text of the last `/CreationDate (` literal (at most 64 bytes, up to its `)`), or None."""
    last = None
    for found in PDF_CREATION.finditer(data):
        last = found
    if last is None:
        return None
    value = data[last.end() : last.end() + 64]
    return value.split(b")", 1)[0].decode("latin-1")


def front_matter_date(text: str) -> str | None:
    """The value of the first `date:` line inside a leading `---` front matter, or None."""
    lines = [line.rstrip("\r") for line in text.split("\n")]
    if not lines or lines[0] != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            return None
        found = FRONT_DATE.match(line)
        if found:
            return found.group(1)
    return None
