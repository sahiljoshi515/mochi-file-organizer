"""An independent implementation of src/plugin/RULES.md, written from that text alone and with other
tools than the plugin's: os.walk, Pillow's EXIF reader, zipfile, xml.dom.minidom, struct, datetime, and
its own patterns and tables. tests/test_differential.py compares it with the plugin, file by file and
step by step; a difference is either a bug in one of them or a gap in RULES.md, fixed there first.
"""

from __future__ import annotations

import codecs
import datetime
import hashlib
import json
import os
import re
import struct
import unicodedata
from xml.dom import minidom
from xml.etree import ElementTree

from PIL import Image

# ----- RULES §2 tables, as written -----

RAW = {"dng", "nef", "cr2", "arw", "orf", "rw2", "pef", "srw", "nrw", "3fr", "erf", "kdc", "mos", "mef", "iiq"}
TEXT = {}
for group, names in (
    ("documents", "txt md rst tex org rtf html"),
    ("images", "svg"),
    ("spreadsheets", "csv tsv"),
    ("data", "json jsonl geojson ipynb xml yaml toml ini cfg conf sql log srt vtt ics vcf bib"),
    ("code", "py js mjs cjs ts tsx jsx c h cc cpp hpp cs java kt go rs rb php swift scala lua pl r sh bash zsh fish ps1 bat css scss less vue svelte dart proto"),
):
    for name in names.split():
        TEXT[name] = group
NORMAL = {"markdown": "md", "yml": "yaml", "htm": "html", "ndjson": "jsonl", "jpeg": "jpg", "jpe": "jpg", "jfif": "jpg", "tif": "tiff"}
FAMILIES = {
    "Word": ("documents", "docx", {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml": "docx",
        "application/vnd.ms-word.document.macroEnabled.main+xml": "docm",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml": "dotx",
        "application/vnd.ms-word.template.macroEnabledTemplate.main+xml": "dotm",
    }),
    "Excel": ("spreadsheets", "xlsx", {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml": "xlsx",
        "application/vnd.ms-excel.sheet.macroEnabled.main+xml": "xlsm",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.template.main+xml": "xltx",
        "application/vnd.ms-excel.template.macroEnabled.main+xml": "xltm",
        "application/vnd.ms-excel.addin.macroEnabled.main+xml": "xlam",
        "application/vnd.ms-excel.sheet.binary.macroEnabled.main": "xlsb",
    }),
    "PowerPoint": ("presentations", "pptx", {
        "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml": "pptx",
        "application/vnd.ms-powerpoint.presentation.macroEnabled.main+xml": "pptm",
        "application/vnd.openxmlformats-officedocument.presentationml.template.main+xml": "potx",
        "application/vnd.ms-powerpoint.template.macroEnabled.main+xml": "potm",
        "application/vnd.openxmlformats-officedocument.presentationml.slideshow.main+xml": "ppsx",
        "application/vnd.ms-powerpoint.slideshow.macroEnabled.main+xml": "ppsm",
        "application/vnd.ms-powerpoint.addin.macroEnabled.main+xml": "ppam",
    }),
}  # fmt: skip
OFFICE_EXTENSIONS = {ext for _group, _plain, types in FAMILIES.values() for ext in types.values()}
TABLE = {"pdf", "png", "jpg", "gif", "webp", "wav", "avi", "heic", "avif", "mov", "m4a", "cr3", "mp4", "tiff", "raf", "mp3", "flac", "ogg", "webm", "mkv", "zip", "gz", "tar", "7z", "rar", "ts", "epub", "odt", "ods", "odp", "jpeg", "jpe", "jfif", "tif"} | OFFICE_EXTENSIONS
CP1252_UNDEFINED = {0x81, 0x8D, 0x8F, 0x90, 0x9D}
JUNK_NAMES = {".ds_store", "thumbs.db", "ehthumbs.db", "ehthumbs_vista.db", "desktop.ini", "icon\r"}
MONTH = {name: number + 1 for number, name in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
ONE_MIB = 1024 * 1024


def claimed(name: str) -> str:
    dot = name.rfind(".")
    if dot <= 0:
        return ""
    tail = name[dot + 1 :]
    if 1 <= len(tail) <= 10 and all(ch.isascii() and ch.isalnum() for ch in tail):
        return tail.lower()
    return ""


def junk(name: str) -> bool:
    low = name.lower()
    return low in JUNK_NAMES or low.startswith(("._", "~$", ".~lock.")) or claimed(name) in ("tmp", "part", "crdownload")


def hidden(name: str) -> bool:
    return name.startswith(".") and not junk(name)


def kept_as_other(ext: str) -> bool:
    """A claimed extension that is not a text extension (normalized) and not in the table's list."""
    return bool(ext) and NORMAL.get(ext, ext) not in TEXT and ext not in TABLE


def wide_text(data: bytes):
    """Row 10: the first byte-order mark of FF FE 00 00, 00 00 FE FF, FF FE, FE FF decides the encoding."""
    for mark, codec in ((b"\xff\xfe\x00\x00", "utf_32_le"), (b"\x00\x00\xfe\xff", "utf_32_be"), (b"\xff\xfe", "utf_16_le"), (b"\xfe\xff", "utf_16_be")):
        if data[: len(mark)] == mark:
            try:
                text = codecs.decode(data[len(mark) :], codec)
            except UnicodeDecodeError:
                return None
            return None if "\0" in text else text
    return None


def utf8_text(data: bytes):
    """Row 19: an optional UTF-8 BOM, then UTF-8 with no NUL."""
    body = data[3:] if data[:3] == b"\xef\xbb\xbf" else data
    try:
        text = codecs.decode(body, "utf_8")
    except UnicodeDecodeError:
        return None
    return None if "\0" in text else text


def legacy_text(data: bytes, ext: str):
    """Row 20: a claimed text extension, no NUL, Windows-1252 without its five undefined bytes, and no
    control character but tab, line feed, form feed and carriage return."""
    if NORMAL.get(ext, ext) not in TEXT or 0 in data or any(byte in CP1252_UNDEFINED for byte in data):
        return None
    text = codecs.decode(data, "cp1252")
    if any((ord(char) < 32 and char not in "\t\n\f\r") or char == "\x7f" for char in text):
        return None
    return text


def as_text(data: bytes, ext: str):
    """The text a text row reads: row 10, else 19, else 20 (a file the rules typed md matched one)."""
    for reader in (wide_text, utf8_text):
        text = reader(data)
        if text is not None:
            return text
    return legacy_text(data, ext)


def nesting(text: str) -> int:
    """How deep arrays and objects nest outside JSON strings, by a plain scan."""
    depth = deepest = 0
    in_string = escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            deepest = max(deepest, depth)
        elif char in "]}":
            depth -= 1
    return deepest


def rfc_json(text: str) -> bool:
    if nesting(text) > 512:
        return False

    def refuse(_constant):
        raise ValueError("not RFC 8259")

    try:
        json.loads(text, parse_constant=refuse, parse_int=lambda digits: 0)
    except (ValueError, RecursionError):
        return False
    return True


def lines_of(text: str) -> list[str]:
    return [line.removesuffix("\r") for line in text.split("\n")]


def text_type(text: str, claimed_ext: str):
    ext = NORMAL.get(claimed_ext, claimed_ext)
    if ext in TEXT:
        return TEXT[ext], ext, ext
    if kept_as_other(claimed_ext):
        return "other", claimed_ext, claimed_ext
    body = text.lstrip()
    first = lines_of(text)[0]
    if body.startswith("<svg"):
        return "images", "svg", "svg"
    if body.startswith("<?xml"):
        close = body.find("?>")
        if 0 <= close and close + 2 <= 4096 and body[close + 2 :].lstrip().startswith("<svg"):
            return "images", "svg", "svg"
    if body[:14].lower().startswith("<!doctype html") or body[:5].lower() == "<html":
        return "documents", "html", "html"
    if body.startswith("{\\rtf"):
        return "documents", "rtf", "rtf"
    if body[:1] in ("{", "[") and rfc_json(text):
        return "data", "json", "json"
    if first.startswith("# ") or first == "---":
        return "documents", "md", "md"
    filled = [line for line in lines_of(text)[:1000] if line.strip() != ""]
    commas = {line.count(",") for line in filled}
    if len(filled) >= 3 and len(commas) == 1 and commas.pop() >= 1:
        return "spreadsheets", "csv", "csv"
    if re.match(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2}", first):
        return "data", "log", "log"
    return "documents", "txt", "txt"


def directory_span(data: bytes):
    """RULES §2: the end record is the last PK 5 6 in the final 65,557 bytes whose comment length reaches
    the end of the file, of the last 16 there; the directory spans from its offset to the record."""
    tail_start = max(0, len(data) - 65557)
    candidates = [tail_start + match.start() for match in re.finditer(re.escape(b"PK\x05\x06"), data[tail_start:])][::-1][:16]
    for at in candidates:
        if at + 22 <= len(data) and at + 22 + struct.unpack("<H", data[at + 20 : at + 22])[0] == len(data):
            (offset,) = struct.unpack("<I", data[at + 16 : at + 20])
            return None if offset == 0xFFFFFFFF or offset > at else (offset, at)
    return None


def find_entry(data: bytes, name: str):
    """The first central-directory header in the span (PK 1 2, 42 bytes with the name's length at 28)
    followed by the name: (flags, method, packed size, local offset), or None."""
    span = directory_span(data)
    if span is None:
        return None
    raw = name.encode()
    header = re.compile(rb"PK\x01\x02[\x00-\xff]{24}" + re.escape(struct.pack("<H", len(raw))) + rb"[\x00-\xff]{16}" + re.escape(raw))
    found = header.search(data, span[0], span[1])
    if found is None:
        return None
    at = found.start()
    flags, method = struct.unpack("<HH", data[at + 8 : at + 12])
    (packed,) = struct.unpack("<I", data[at + 20 : at + 24])
    (offset,) = struct.unpack("<I", data[at + 42 : at + 46])
    return flags, method, packed, offset


def zip_entry(data: bytes, name: str):
    """A part's first 4,096 bytes, decoding at most 4 DEFLATE blocks (puff_prefix), or None."""
    entry = find_entry(data, name)
    if entry is None:
        return None
    flags, method, packed, offset = entry
    if flags & 1 or method not in (0, 8) or data[offset : offset + 4] != b"PK\x03\x04" or offset + 30 > len(data):
        return None
    name_length, extra_length = struct.unpack("<HH", data[offset + 26 : offset + 30])
    start = offset + 30 + name_length + extra_length
    if start + packed > len(data):
        return None
    if method == 0:
        return data[start : start + min(packed, 4096)]
    return puff_prefix(data[start : start + packed], 4096, 4)


def puff_prefix(stream: bytes, limit: int, blocks: int):
    """Raw DEFLATE decoded bit by bit, as Mark Adler's puff.c does: the first `limit` bytes, reading at
    most `blocks` blocks; None when what is read is not valid."""
    position = [0, 0]  # byte, bit

    def bits(count):
        value = 0
        for shift in range(count):
            byte, bit = position
            if byte >= len(stream):
                raise ValueError("early end")
            value |= ((stream[byte] >> bit) & 1) << shift
            position[1] += 1
            if position[1] == 8:
                position[0], position[1] = byte + 1, 0
        return value

    def build(lengths):
        counts = [0] * 16
        for length in lengths:
            counts[length] += 1
        left = 1
        for length in range(1, 16):
            left = (left << 1) - counts[length]
            if left < 0:
                raise ValueError("over-subscribed")
        offsets = [0] * 17
        for length in range(1, 16):
            offsets[length + 1] = offsets[length] + counts[length]
        symbols = [0] * offsets[16]
        for symbol, length in enumerate(lengths):
            if length:
                symbols[offsets[length]] = symbol
                offsets[length] += 1
        return counts, symbols, left

    def decode(code_table):
        counts, symbols, _left = code_table
        code = first = index = 0
        for length in range(1, 16):
            code |= bits(1)
            count = counts[length]
            if code - count < first:
                return symbols[index + (code - first)]
            index += count
            first = (first + count) << 1
            code <<= 1
        raise ValueError("no such code")

    base = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258]
    extra = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0]
    dbase = [1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577]
    dextra = [0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13]
    order = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15]
    out = bytearray()
    try:
        for _block in range(blocks):
            last, kind = bits(1), bits(2)
            if kind == 0:
                if position[1]:
                    position[0], position[1] = position[0] + 1, 0
                at = position[0]
                if at + 4 > len(stream):
                    raise ValueError("stored early end")
                length, check = struct.unpack("<HH", stream[at : at + 4])
                if length != (~check & 0xFFFF) or at + 4 + length > len(stream):
                    raise ValueError("stored")
                out += stream[at + 4 : at + 4 + length]
                position[0] = at + 4 + length
            else:
                if kind == 1:
                    literal = build([8] * 144 + [9] * 112 + [7] * 24 + [8] * 8)
                    distance = build([5] * 30)
                elif kind == 2:
                    nlen, ndist, ncode = bits(5) + 257, bits(5) + 1, bits(4) + 4
                    if nlen > 286 or ndist > 30:
                        raise ValueError("counts")
                    code_lengths = [0] * 19
                    for index in range(ncode):
                        code_lengths[order[index]] = bits(3)
                    length_code = build(code_lengths)
                    if length_code[2] != 0:
                        raise ValueError("incomplete code-length code")
                    lengths = []
                    while len(lengths) < nlen + ndist:
                        symbol = decode(length_code)
                        if symbol < 16:
                            lengths.append(symbol)
                            continue
                        if symbol == 16:
                            if not lengths:
                                raise ValueError("repeat")
                            value, repeat = lengths[-1], 3 + bits(2)
                        elif symbol == 17:
                            value, repeat = 0, 3 + bits(3)
                        else:
                            value, repeat = 0, 11 + bits(7)
                        if len(lengths) + repeat > nlen + ndist:
                            raise ValueError("too many")
                        lengths += [value] * repeat
                    if lengths[256] == 0:
                        raise ValueError("no end")
                    literal, distance = build(lengths[:nlen]), build(lengths[nlen:])
                    for table, count in ((literal, nlen), (distance, ndist)):
                        if table[2] and count - table[0][0] != table[0][1]:
                            raise ValueError("incomplete")
                else:
                    raise ValueError("type 3")
                while len(out) < limit:
                    symbol = decode(literal)
                    if symbol < 256:
                        out.append(symbol)
                    elif symbol == 256:
                        break
                    else:
                        symbol -= 257
                        if symbol >= 29:
                            raise ValueError("length")
                        length = base[symbol] + bits(extra[symbol])
                        symbol = decode(distance)
                        if symbol >= 30:
                            raise ValueError("distance")
                        back = dbase[symbol] + bits(dextra[symbol])
                        if back > len(out):
                            raise ValueError("too far")
                        for _ in range(length):
                            out.append(out[-back])
            if len(out) >= limit or last:
                break
    except ValueError:
        return None
    return bytes(out[:limit])


MPEG_KBITS = {
    ("1", 1): [32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448],
    ("1", 2): [32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384],
    ("1", 3): [32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
    ("2", 1): [32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256],
    ("2", 2): [8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
    ("2", 3): [8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
}
MPEG_RATES = {"1": [44100, 48000, 32000], "2": [22050, 24000, 16000], "2.5": [11025, 12000, 8000]}


def frame(data: bytes, at: int):
    """An MPEG audio frame header at `at`: (version, layer, length), or None."""
    if len(data) < at + 4:
        return None
    (word,) = struct.unpack(">I", data[at : at + 4])
    if word >> 21 != 0x7FF:
        return None
    version = {0b11: "1", 0b10: "2", 0b00: "2.5"}.get((word >> 19) & 3)
    layer = {0b11: 1, 0b10: 2, 0b01: 3}.get((word >> 17) & 3)
    rate_index, bitrate_index, padding = (word >> 10) & 3, (word >> 12) & 15, (word >> 9) & 1
    if version is None or layer is None or bitrate_index in (0, 15) or rate_index == 3:
        return None
    bits = MPEG_KBITS[("1" if version == "1" else "2"), layer][bitrate_index - 1] * 1000
    rate = MPEG_RATES[version][rate_index]
    if layer == 1:
        length = (12 * bits // rate + padding) * 4
    elif layer == 3 and version != "1":
        length = 72 * bits // rate + padding
    else:
        length = 144 * bits // rate + padding
    return version, layer, length


def mpeg(data: bytes) -> bool:
    first = frame(data, 0)
    if first is None:
        return False
    if len(data) < first[2] + 4:
        return True
    second = frame(data, first[2])
    return second is not None and second[:2] == first[:2]


def classic_quicktime(data: bytes) -> bool:
    if len(data) < 8 or data[4:8] not in (b"moov", b"mdat", b"wide", b"free", b"skip", b"pnot"):
        return False
    (size,) = struct.unpack(">I", data[:4])
    if size == 0:
        return True
    if size == 1:
        return len(data) >= 16 and 16 <= struct.unpack(">Q", data[8:16])[0] <= len(data)
    return 8 <= size <= len(data)


def transport_stream(data: bytes) -> bool:
    packets = min(20, len(data) // 188)
    return packets >= 3 and all(data[188 * k] == 0x47 for k in range(packets))


def content_types(data: bytes, part: str):
    """The ContentType of the first Override for `/part`, else of the first Default for its extension,
    among the elements an incremental XML parser sees in the part's first 4,096 bytes."""
    content = zip_entry(data, "[Content_Types].xml")
    if content is None:
        return None
    parser = ElementTree.XMLPullParser(events=("start",))
    elements = []
    try:
        parser.feed(content.decode("utf-8", "replace"))
        elements = [element for _event, element in parser.read_events()]
    except ElementTree.ParseError:
        elements = [element for _event, element in parser.read_events()]
    local = [(element.tag.rpartition("}")[2], element.attrib) for element in elements]
    for tag, attributes in local:
        if tag == "Override" and attributes.get("PartName", "").lower() == "/" + part.lower():
            return attributes.get("ContentType")
    extension = part.rsplit(".", 1)[1].lower()
    for tag, attributes in local:
        if tag == "Default" and attributes.get("Extension", "").lower() == extension:
            return attributes.get("ContentType")
    return None


def office(data: bytes, ext: str):
    for family, parts in (("Word", ["word/document.xml"]), ("Excel", ["xl/workbook.xml", "xl/workbook.bin"]), ("PowerPoint", ["ppt/presentation.xml"])):
        present = [part for part in parts if find_entry(data, part) is not None]
        if not present:
            continue
        group, plain, types = FAMILIES[family]
        found = content_types(data, present[0])
        chosen = {kind.lower(): value for kind, value in types.items()}.get((found or "").lower())
        if chosen is None:
            chosen = ext if ext in types.values() else plain
        return group, chosen, chosen
    return None


def kind_of(data: bytes, name: str):
    """RULES §2: (group, type, ext)."""
    ext = claimed(name)
    if data[:5] == b"%PDF-":
        return "documents", "pdf", "pdf"
    if data[:8] == bytes.fromhex("89504E470D0A1A0A"):
        return "images", "png", "png"
    if data[:3] == b"\xff\xd8\xff":
        return "images", "jpg", "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "images", "gif", "gif"
    if data[:4] == b"RIFF" and len(data) >= 12:
        form = data[8:12]
        for tag, triple in ((b"WEBP", ("images", "webp", "webp")), (b"WAVE", ("audio", "wav", "wav")), (b"AVI ", ("video", "avi", "avi"))):
            if form == tag:
                return triple
    if len(data) >= 12 and data[4:8] == b"ftyp":
        (box_size,) = struct.unpack(">I", data[:4])
        major = data[8:12]
        end = min(len(data), box_size, 16 + 4 * 1024) if box_size >= 16 else 16
        brands = [data[at : at + 4] for at in range(16, end - 3, 4)]
        if major in (b"avif", b"avis") or (major in (b"mif1", b"msf1") and any(brand in (b"avif", b"avis") for brand in brands)):
            return "images", "avif", "avif"
        if major in (b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"):
            return "images", "heic", "heic"
        if major == b"qt  ":
            return "video", "mov", "mov"
        if major in (b"M4A ", b"M4B "):
            return "audio", "m4a", "m4a"
        if major == b"crx ":
            return "images", "raw", "cr3"
        return "video", "mp4", "mp4"
    if classic_quicktime(data):
        return "video", "mov", "mov"
    if data[:4] in (b"II*\0", b"MM\0*"):
        return ("images", "raw", ext) if ext in RAW else ("images", "tiff", "tiff")
    if data[:15] == b"FUJIFILMCCD-RAW":
        return "images", "raw", "raf"
    text = wide_text(data)
    if text is not None:
        return text_type(text, ext)
    if (data[:3] == b"ID3" and len(data) > 3 and data[3] in (2, 3, 4)) or mpeg(data):
        return "audio", "mp3", "mp3"
    if data[:4] == b"fLaC":
        return "audio", "flac", "flac"
    if data[:4] == b"OggS":
        return "audio", "ogg", "ogg"
    if data[:4] == bytes.fromhex("1A45DFA3"):
        return ("video", "webm", "webm") if b"webm" in data[:64] else ("video", "mkv", "mkv")
    if data[:4] in (b"PK\x03\x04", b"PK\x05\x06"):
        found = office(data, ext)
        if found:
            return found
        if find_entry(data, "mimetype") is not None:
            content = zip_entry(data, "mimetype")
            mimes = {
                b"application/vnd.oasis.opendocument.text": ("documents", "odt"),
                b"application/vnd.oasis.opendocument.spreadsheet": ("spreadsheets", "ods"),
                b"application/vnd.oasis.opendocument.presentation": ("presentations", "odp"),
                b"application/epub+zip": ("documents", "epub"),
            }
            if content in mimes:
                group, kind = mimes[content]
                return group, kind, kind
        return ("other", ext, ext) if kept_as_other(ext) else ("archives", "zip", "zip")
    if data[:2] == b"\x1f\x8b":
        low = name.lower()
        return "archives", "gz", ("tar.gz" if low.endswith((".tar.gz", ".tgz")) else "gz")
    if data[257:262] == b"ustar":
        return "archives", "tar", "tar"
    if data[:6] == bytes.fromhex("377ABCAF271C"):
        return "archives", "7z", "7z"
    if data[:6] == b"Rar!\x1a\x07":
        return "archives", "rar", "rar"
    text = utf8_text(data)
    if text is None:
        text = legacy_text(data, ext)
    if text is not None:
        return text_type(text, ext)
    if transport_stream(data):
        return "video", "ts", "ts"
    return ("other", ext, ext) if kept_as_other(ext) else ("other", "bin", "bin")


# ----- RULES §3: dates -----


def calendar(year: int, month: int, day: int, low: int, high: int):
    if not low <= year <= high:
        return None
    try:
        return datetime.date(year, month, day).isoformat()
    except ValueError:
        return None


def exif_original(tiff_or_exif: bytes, in_first_ifd: bool = False):
    """Pillow reads the TIFF; the Exif IFD's 9003 (or IFD0's, for a CR3 CMT2 box) as an ASCII string, or None."""
    try:
        exif = Image.Exif()
        exif.load(tiff_or_exif)
        value = exif.get(0x9003) if in_first_ifd else exif.get_ifd(0x8769).get(0x9003)
    except Exception:  # noqa: BLE001 - any unreadable TIFF gives no date
        return None
    if isinstance(value, bytes):
        value = value.decode("latin-1")
    if not isinstance(value, str):
        return None
    found = re.match(r"([0-9]{4}):([0-9]{2}):([0-9]{2})", value)
    return calendar(*map(int, found.groups()), 1971, 2099) if found else None


def jpeg_date(data: bytes):
    """Walk the JPEG's first 64 markers (fill bytes count) to the first APP1 Exif segment before SOS."""
    at = 2
    for _marker in range(64):
        if not (at + 4 <= len(data) and data[at] == 0xFF):
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
        (length,) = struct.unpack(">H", data[at + 2 : at + 4])
        if length < 2 or at + 2 + length > len(data):
            return None
        segment = data[at + 4 : at + 2 + length]
        if marker == 0xE1 and segment[:6] == b"Exif\0\0":
            return exif_original(segment)
        at += 2 + length
    return None


def png_date(data: bytes):
    chunks = []
    at = 8
    while at + 12 <= len(data) and len(chunks) < 1024:
        (length,) = struct.unpack(">I", data[at : at + 4])
        kind = data[at + 4 : at + 8]
        if at + 12 + length > len(data):
            break
        chunks.append((kind, data[at + 8 : at + 8 + length]))
        if kind == b"IEND":
            break
        at += 12 + length
    for kind, body in chunks:
        if kind == b"eXIf":
            found = exif_original(body if body[:6] == b"Exif\0\0" else b"Exif\0\0" + body)
            if found:
                return found
            break
    for kind, body in chunks:
        if kind == b"tEXt" and body.split(b"\0", 1)[0] == b"Creation Time":
            text = body.split(b"\0", 1)[1][:64].decode("latin-1") if b"\0" in body else ""
            iso = re.match(r"\s*([0-9]{4})-([0-9]{2})-([0-9]{2})", text)
            if iso:
                found = calendar(*map(int, iso.groups()), 1971, 2099)
                if found:
                    return found
            rfc = re.match(r"\s*(?:[A-Za-z]{3},\s*)?([0-9]{1,2})\s+([A-Za-z]{3})\s+([0-9]{4})", text)
            if rfc and rfc.group(2).lower() in MONTH:
                return calendar(int(rfc.group(3)), MONTH[rfc.group(2).lower()], int(rfc.group(1)), 1971, 2099)
            return None
    return None


def webp_date(data: bytes):
    at = 12
    for _chunk in range(1024):
        if at + 8 > len(data):
            return None
        fourcc = data[at : at + 4]
        (size,) = struct.unpack("<I", data[at + 4 : at + 8])
        if at + 8 + size > len(data):
            return None
        if fourcc == b"EXIF":
            body = data[at + 8 : at + 8 + size]
            return exif_original(body if body[:6] == b"Exif\0\0" else b"Exif\0\0" + body)
        at += 8 + size + size % 2
    return None


def pdf_date(data: bytes):
    """The document information dictionary's CreationDate: the last /Info N G R names it; written out
    plainly, its literal decides; otherwise the last CreationDate literal in the file."""
    where = data
    references = re.findall(rb"/Info\s+([0-9]+)\s+([0-9]+)\s+R", data)
    if references:
        number, generation = references[-1]
        headers = [match.end() for match in re.finditer(rb"(?<![0-9])" + number + rb"\s+" + generation + rb"\s+obj\b", data)]
        if headers:
            close = data.find(b"endobj", headers[-1])
            if close >= 0:
                where = data[headers[-1] : close]
                inside = re.search(rb"/CreationDate\s*\(", where)
                return pdf_value(data, headers[-1] + inside.end()) if inside else None
    found = list(re.finditer(rb"/CreationDate\s*\(", where))
    return pdf_value(data, found[-1].end()) if found else None


def pdf_value(data: bytes, after: int):
    value = data[after : after + 64].split(b")")[0].decode("latin-1")
    parts = re.match(r"(?:D:)?([0-9]{4})([0-9]{2})([0-9]{2})", value)
    return calendar(*map(int, parts.groups()), 1971, 2099) if parts else None


def xml_date(data: bytes, member: str, tag: str):
    content = zip_entry(data, member)
    if content is None:
        return None
    # the first element written exactly `tag` (prefix included); minidom keeps prefixes in tagName
    try:
        document = minidom.parseString(content)
        elements = document.getElementsByTagName(tag)
    except Exception:  # noqa: BLE001 - not XML: fall back to the literal opening tag, as the rule reads it
        elements = None
    if elements is not None:
        if not elements:
            return None
        text = "".join(node.data for node in elements[0].childNodes if node.nodeType == node.TEXT_NODE)
    else:
        literal = re.search(r"<" + re.escape(tag) + r"(?:\s[^>]*)?>([^<]*)", content.decode("utf-8", "replace"))
        if not literal:
            return None
        text = literal.group(1)
    found = re.match(r"\s*([0-9]{4})-([0-9]{2})-([0-9]{2})", text)
    return calendar(*map(int, found.groups()), 1971, 2099) if found else None


def media_date(data: bytes):
    def walk_boxes(start: int, end: int):
        at, seen = start, 0
        while at + 8 <= end and seen < 1024:
            seen += 1
            (size,) = struct.unpack(">I", data[at : at + 4])
            kind = data[at + 4 : at + 8]
            header = 8
            if size == 1:
                if at + 16 > end:
                    return
                (size,) = struct.unpack(">Q", data[at + 8 : at + 16])
                header = 16
            elif size == 0:
                size = end - at
            if size < header or at + size > end:
                return
            yield kind, at + header, at + size
            at += size

    for kind, start, end in walk_boxes(0, len(data)):
        if kind == b"moov":
            for inner, body, body_end in walk_boxes(start, end):
                if inner == b"mvhd":
                    if body >= body_end:
                        return None
                    width = 8 if data[body] == 1 else 4
                    if body + 4 + width > body_end:
                        return None
                    seconds = int.from_bytes(data[body + 4 : body + 4 + width], "big")
                    if seconds == 0:
                        return None
                    moment = datetime.datetime(1904, 1, 1) + datetime.timedelta(seconds=seconds)
                    return calendar(moment.year, moment.month, moment.day, 1971, 2099)
            return None
    return None


def heif_item_date(data: bytes):
    """The Exif item of a HEIF/AVIF file, found by walking meta/iinf/iloc with struct."""

    def children(start: int, end: int):
        at, seen = start, 0
        while at + 8 <= end and seen < 1024:
            seen += 1
            size, kind = struct.unpack(">I4s", data[at : at + 8])
            header = 8
            if size == 1:
                size = struct.unpack(">Q", data[at + 8 : at + 16])[0]
                header = 16
            elif size == 0:
                size = end - at
            if size < header or at + size > end:
                return
            yield kind, at + header, at + size
            at += size

    def read(at: int, width: int) -> int:
        if width == 0:
            return 0
        if at + width > len(data):
            raise IndexError("past the end")
        return int.from_bytes(data[at : at + width], "big")

    try:
        meta = next(((start, end) for kind, start, end in children(0, len(data)) if kind == b"meta"), None)
        if meta is None:
            return None
        exif_ids, places, idat = None, None, None
        for kind, start, end in children(meta[0] + 4, meta[1]):
            if kind == b"iinf" and exif_ids is None:
                exif_ids = []
                width = 2 if data[start] == 0 else 4
                for entry, body, _body_end in children(start + 4 + width, end):
                    if entry == b"infe" and data[body] >= 2:
                        id_width = 2 if data[body] == 2 else 4
                        if data[body + 4 + id_width + 2 : body + 4 + id_width + 6] == b"Exif":
                            exif_ids.append(read(body + 4, id_width))
            elif kind == b"iloc" and places is None:
                places = {}
                version = data[start]
                offset_size, length_size = data[start + 4] >> 4, data[start + 4] & 0x0F
                base_size = data[start + 5] >> 4
                index_size = data[start + 5] & 0x0F if version in (1, 2) else 0
                id_width = 4 if version == 2 else 2
                at = start + 6
                count = read(at, id_width)
                at += id_width
                budget = 1024
                for _ in range(min(count, 1024)):
                    item = read(at, id_width)
                    at += id_width
                    method = 0
                    if version in (1, 2):
                        method = read(at, 2) & 0x0F
                        at += 2
                    at += 2
                    base = read(at, base_size)
                    at += base_size
                    extents = read(at, 2)
                    at += 2
                    if extents > budget:
                        break
                    budget -= extents
                    spans = []
                    for _ in range(extents):
                        at += index_size
                        offset = read(at, offset_size)
                        at += offset_size
                        length = read(at, length_size)
                        at += length_size
                        spans.append((offset, length))
                    places.setdefault(item, (method, base, spans))
            elif kind == b"idat" and idat is None:
                idat = start
        if not exif_ids or places is None or exif_ids[0] not in places:
            return None
        method, base, spans = places[exif_ids[0]]
        if method == 1 and idat is None or method not in (0, 1):
            return None
        origin = base + (idat if method == 1 else 0)
        payload = b"".join(data[origin + offset : origin + offset + length] if length else data[origin + offset :] for offset, length in spans)[: 1 << 20]
        (skip,) = struct.unpack(">I", payload[:4])
        tiff = payload[4 + skip :]
        if tiff[:6] == b"Exif\0\0":
            tiff = tiff[6:]
        return exif_original(tiff) if tiff[:4] in (b"II*\0", b"MM\0*") else None
    except (IndexError, struct.error):
        return None


def boxes_in(data: bytes, start: int, end: int):
    at, seen = start, 0
    while at + 8 <= end and seen < 1024:
        seen += 1
        size, kind = struct.unpack(">I4s", data[at : at + 8])
        header = 8
        if size == 1:
            if at + 16 > end:
                return
            size, header = struct.unpack(">Q", data[at + 8 : at + 16])[0], 16
        elif size == 0:
            size = end - at
        if size < header or at + size > end:
            return
        yield kind, at + header, at + size
        at += size


def cr3_date(data: bytes):
    """moov -> the Canon uuid box -> CMT2 (tag 9003 in its first IFD), else CMT1 -> Exif IFD -> 9003."""
    canon = uuid_bytes("85c0b687-820f-11e0-8111-f4ce462b6a48")
    for kind, start, end in boxes_in(data, 0, len(data)):
        if kind != b"moov":
            continue
        for inner, body, body_end in boxes_in(data, start, end):
            if inner == b"uuid" and data[body : body + 16] == canon:
                parts = {}
                for name, part, part_end in boxes_in(data, body + 16, body_end):
                    parts.setdefault(name, data[part:part_end])
                found = exif_original(b"Exif\0\0" + parts[b"CMT2"], in_first_ifd=True) if b"CMT2" in parts else None
                if found is None and b"CMT1" in parts:
                    found = exif_original(b"Exif\0\0" + parts[b"CMT1"])
                return found
        return None
    return None


def uuid_bytes(text: str) -> bytes:
    return bytes.fromhex(text.replace("-", ""))


def front_matter_date(text: str):
    lines = lines_of("\n".join(text.split("\n")[:1000]))
    if lines[0] != "---":
        return None
    for line in lines[1:]:
        if line.strip(" \t") == "---":
            return None
        if line.startswith("date:"):
            value = line[len("date:") :].strip(" \t").strip("'\"")
            found = re.match(r"([0-9]{4})-([0-9]{2})-([0-9]{2})", value)
            return calendar(*map(int, found.groups()), 1971, 2099) if found else None
    return None


def embedded_date(kind: str, ext: str, data: bytes, claimed_of_ext: str):
    if kind == "jpg":
        return jpeg_date(data)
    if kind == "tiff" or (kind == "raw" and data[:4] in (b"II*\0", b"MM\0*")):
        return exif_original(data)
    if kind in ("heic", "avif"):
        return heif_item_date(data)
    if kind == "raw" and ext == "cr3":
        return cr3_date(data)
    if kind == "webp":
        return webp_date(data)
    if kind == "png":
        return png_date(data)
    if kind == "pdf":
        return pdf_date(data)
    if kind in OFFICE_EXTENSIONS:
        return xml_date(data, "docProps/core.xml", "dcterms:created")
    if kind in ("odt", "ods", "odp"):
        return xml_date(data, "meta.xml", "meta:creation-date")
    if kind in ("mp4", "mov", "m4a"):
        return media_date(data)
    if kind == "md":
        text = as_text(data, claimed_of_ext)
        return front_matter_date(text) if text is not None else None
    return None


# ----- RULES §3 step 2 and §4: names -----

SCHEME = re.compile(r"^([0-9]{4}-[0-9]{2}-[0-9]{2}|undated)_([a-z0-9]+(?:-[a-z0-9]+)*)(?:_([2-9]|[1-9][0-9]+))?\.(tar\.gz|[a-z0-9]{1,10})$")
DATE_IN_NAME = re.compile(r"(?<![0-9])([0-9]{4})([-_.]?)([0-9]{2})\2([0-9]{2})(?![0-9])")
TAIL = re.compile(r"(?:\s*\([0-9]+\)|\s+-\s+copy(?:\s+\([0-9]+\))?|\s+copy(?:\s+[0-9]+)?|[_-]copy[0-9]*)$")


def stem(name: str, ext: str) -> str:
    low = name.lower()
    if ext == "tar.gz":
        for ending in (".tar.gz", ".tgz"):
            if low.endswith(ending) and len(name) > len(ending):
                return name[: -len(ending)]
    return name[: name.rfind(".")] if claimed(name) else name


def date_in(text: str):
    for found in DATE_IN_NAME.finditer(text):
        date = calendar(int(found.group(1)), int(found.group(3)), int(found.group(4)), 1990, 2039)
        if date:
            return date, found.span()
    return None


def slug(text: str) -> str:
    dated = date_in(text)
    if dated:
        text = text[: dated[1][0]] + text[dated[1][1] :]
    text = "".join(char for char in unicodedata.normalize("NFKD", text) if char.isascii()).lower()
    while text.startswith("copy of "):
        text = text[len("copy of ") :]
    while TAIL.search(text):
        text = TAIL.sub("", text, count=1)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    text = text[:60].rstrip("-")
    return text or "file"


def name_date_and_slug(name: str, ext: str):
    scheme = SCHEME.match(name)
    if scheme:
        date = None
        if scheme.group(1) != "undated":
            year, month, day = map(int, scheme.group(1).split("-"))
            date = calendar(year, month, day, 1971, 2099)
        return date, scheme.group(2)
    base = stem(name, ext)
    dated = date_in(base)
    return (dated[0] if dated else None), slug(base)


# ----- facts, the plan -----


def facts(path: str, data: bytes) -> dict:
    name = path.split("/")[-1]
    group, kind, ext = kind_of(data, name)
    named, made_slug = name_date_and_slug(name, ext)
    date = embedded_date(kind, ext, data, claimed(name)) or named
    is_junk = junk(name)
    base = None
    if not is_junk and data:
        folder = date[:4] if date else "undated"
        base = f"organized/{group}/{kind}/{folder}/{date or 'undated'}_{made_slug}.{ext}"
    conforming = False
    if base is not None:
        conforming = path == base or re.fullmatch(re.escape(base[: -len(ext) - 1]) + r"_(?:[2-9]|[1-9][0-9]+)\." + re.escape(ext), path) is not None
    return {
        "path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "junk": is_junk, "group": group,
        "type": kind, "ext": ext, "date": date, "slug": made_slug, "base": base, "conforming": conforming,
    }  # fmt: skip


def caseless(path: str) -> str:
    return unicodedata.normalize("NFD", unicodedata.normalize("NFD", path).casefold())


def copy_marker(name: str, ext: str) -> bool:
    """RULES §4: not in scheme form, and slug step 3 or 4 strips something."""
    if SCHEME.match(name):
        return False
    text = stem(name, ext)
    dated = date_in(text)
    if dated:
        text = text[: dated[1][0]] + text[dated[1][1] :]
    text = "".join(char for char in unicodedata.normalize("NFKD", text) if char.isascii()).lower()
    return text.startswith("copy of ") or TAIL.search(text) is not None


def names_its_type(name: str, ext: str) -> bool:
    aliases = {"jpg": ["jpeg", "jpe", "jfif"], "tiff": ["tif"], "md": ["markdown"], "yaml": ["yml"], "html": ["htm"], "jsonl": ["ndjson"], "tar.gz": ["tgz"]}
    return any(name.lower().endswith("." + tail) for tail in [ext, *aliases.get(ext, [])])


def survey_folder(root: str):
    """(files that take part, every path that is taken) under `root`, by RULES §1 and §5, with os.walk:
    hidden folders are not entered; a folder holding no file and no hidden entry is not taken."""
    files, folders_seen, holding = [], [], set()
    for here, folders, names in os.walk(root):
        relative = os.path.relpath(here, root)
        prefix = "" if relative == "." else relative.replace(os.sep, "/") + "/"
        for folder in list(folders):
            if folder.startswith("."):
                folders.remove(folder)
                holding.add(prefix + folder)
            else:
                folders_seen.append(prefix + folder)
        for name in names:
            if not hidden(name):
                files.append(prefix + name)
            holding.add(prefix + name)
    alive = set()
    for path in holding:
        parts = path.split("/")
        alive.update("/".join(parts[:end]) for end in range(1, len(parts)))
    taken = sorted(files + [folder for folder in folders_seen if folder in alive])
    return sorted(files), taken


def organize(root: str) -> dict:
    """The rules applied to the folder at `root`: every file's facts, in order, and every step."""
    files, paths = survey_folder(root)
    found = [facts(path, open(os.path.join(root, path), "rb").read()) for path in files]  # noqa: SIM115

    def place(item):
        name = item["path"].split("/")[-1]
        return (not item["conforming"], copy_marker(name, item["ext"]), not names_its_type(name, item["ext"]), item["path"].count("/"), item["path"])

    order = sorted(found, key=place)
    taken = {caseless(path) for path in paths if caseless(path) == "organized" or caseless(path).startswith("organized/")}
    kept_at: dict[str, int] = {}
    steps = []
    actions = 0
    for index, item in enumerate(order):
        if item["junk"]:
            step = ("delete", "junk", None, None)
        elif item["size"] == 0:
            step = ("delete", "empty", None, None)
        elif item["sha256"] in kept_at:
            step = ("delete", "copy", kept_at[item["sha256"]], None)
        elif item["conforming"]:
            kept_at[item["sha256"]] = index
            step = ("stay", "in-place", None, item["path"])
        else:
            kept_at[item["sha256"]] = index
            number, base, ext = 1, item["base"], item["ext"]
            while True:
                candidate = base if number == 1 else f"{base[: -len(ext) - 1]}_{number}.{ext}"
                if caseless(candidate) not in taken:
                    break
                number += 1
            taken.add(caseless(candidate))
            step = ("move", "rules", None, candidate)
        in_quota = step[0] != "stay" and actions < 60
        actions += step[0] != "stay"
        steps.append({"i": index, "path": item["path"], "action": step[0], "reason": step[1], "copy_of": step[2], "target": step[3], "quota": in_quota})
    return {"files": order, "steps": steps}
