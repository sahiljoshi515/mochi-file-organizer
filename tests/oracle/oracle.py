"""An independent implementation of src/plugin/RULES.md, written from that text alone and with other
tools than the plugin's: os.walk, Pillow's EXIF reader, zipfile, xml.dom.minidom, struct, datetime, and
its own patterns and tables. tests/test_differential.py compares it with the plugin, file by file and
step by step; a difference is either a bug in one of them or a gap in RULES.md, fixed there first.
"""

from __future__ import annotations

import datetime
import hashlib
import io
import json
import os
import re
import struct
import unicodedata
import zipfile
from xml.dom import minidom

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
NORMAL = {"markdown": "md", "yml": "yaml", "htm": "html", "ndjson": "jsonl"}
TABLE = {"pdf", "png", "jpg", "gif", "webp", "wav", "avi", "heic", "avif", "mov", "m4a", "cr3", "mp4", "tiff", "raf", "mp3", "flac", "ogg", "webm", "mkv", "docx", "xlsx", "pptx", "odt", "ods", "odp", "epub", "zip", "gz", "tar", "7z", "rar"}
NEVER_KEPT = {"jpeg", "jpe", "jfif", "tif"}
JUNK_NAMES = {".ds_store", "thumbs.db", "ehthumbs.db", "ehthumbs_vista.db", "desktop.ini", "icon\r"}
MONTH = {name: number + 1 for number, name in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
FOUR_MIB = 4 * 1024 * 1024
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
    return bool(ext) and ext not in TEXT and ext not in NORMAL and ext not in TABLE and ext not in NEVER_KEPT


def as_text(data: bytes):
    body = data[3:] if data[:3] == b"\xef\xbb\xbf" else data
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return None if "\0" in text else text


def lines_of(text: str) -> list[str]:
    return [line.removesuffix("\r") for line in text.split("\n")]


def text_type(text: str, ext: str):
    ext = NORMAL.get(ext, ext)
    if ext in TEXT:
        return TEXT[ext], ext, ext
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
    if body[:1] in ("{", "["):
        try:
            json.loads(text)
            return "data", "json", "json"
        except (ValueError, RecursionError):
            pass
    if first.startswith("# ") or first == "---":
        return "documents", "md", "md"
    filled = [line for line in lines_of(text) if line.strip() != ""]
    commas = {line.count(",") for line in filled}
    if len(filled) >= 3 and len(commas) == 1 and commas.pop() >= 1:
        return "spreadsheets", "csv", "csv"
    if re.match(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2}", first):
        return "data", "log", "log"
    return "documents", "txt", "txt"


def zip_names(data: bytes):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return archive.infolist()
    except (zipfile.BadZipFile, OSError, ValueError, EOFError, KeyError, NotImplementedError):
        return None


def zip_entry(data: bytes, name: str):
    """An entry's bytes when it is stored or deflated, unencrypted and at most 1 MiB; else None."""
    infos = zip_names(data)
    if not infos:
        return None
    for info in infos:
        if info.filename == name:
            if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED) or info.flag_bits & 1:
                return None
            if info.file_size > ONE_MIB or info.compress_size > ONE_MIB:
                return None
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    return archive.read(info)
            except (zipfile.BadZipFile, OSError, ValueError, EOFError, KeyError, NotImplementedError):
                return None
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
        end = min(len(data), box_size) if box_size >= 16 else 16
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
    if data[:4] in (b"II*\0", b"MM\0*"):
        return ("images", "raw", ext) if ext in RAW else ("images", "tiff", "tiff")
    if data[:15] == b"FUJIFILMCCD-RAW":
        return "images", "raw", "raf"
    if (data[:3] == b"ID3" and len(data) > 3 and data[3] in (2, 3, 4)) or (
        len(data) >= 3
        and data[0] == 0xFF
        and (data[1] >> 5) == 0b111
        and ((data[1] >> 3) & 0b11) != 0b01
        and ((data[1] >> 1) & 0b11) != 0b00
        and (data[2] >> 4) != 0b1111
        and ((data[2] >> 2) & 0b11) != 0b11
    ):
        return "audio", "mp3", "mp3"
    if data[:4] == b"fLaC":
        return "audio", "flac", "flac"
    if data[:4] == b"OggS":
        return "audio", "ogg", "ogg"
    if data[:4] == bytes.fromhex("1A45DFA3"):
        return ("video", "webm", "webm") if b"webm" in data[:64] else ("video", "mkv", "mkv")
    if data[:4] in (b"PK\x03\x04", b"PK\x05\x06"):
        infos = zip_names(data) or []
        names = [info.filename for info in infos]
        for part, group, kind in (("word/document.xml", "documents", "docx"), ("xl/workbook.xml", "spreadsheets", "xlsx"), ("ppt/presentation.xml", "presentations", "pptx")):
            if part in names:
                return group, kind, kind
        if "mimetype" in names:
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
    text = as_text(data)
    if text is not None:
        return text_type(text, ext)
    return ("other", ext, ext) if kept_as_other(ext) else ("other", "bin", "bin")


# ----- RULES §3: dates -----


def calendar(year: int, month: int, day: int, low: int, high: int):
    if not low <= year <= high:
        return None
    try:
        return datetime.date(year, month, day).isoformat()
    except ValueError:
        return None


def exif_original(tiff_or_exif: bytes):
    """Pillow reads the TIFF; the Exif IFD's 9003 as an ASCII string, or None."""
    try:
        exif = Image.Exif()
        exif.load(tiff_or_exif)
        value = exif.get_ifd(0x8769).get(0x9003)
    except Exception:  # noqa: BLE001 - any unreadable TIFF gives no date
        return None
    if isinstance(value, bytes):
        value = value.decode("latin-1")
    if not isinstance(value, str):
        return None
    found = re.match(r"([0-9]{4}):([0-9]{2}):([0-9]{2})", value)
    return calendar(*map(int, found.groups()), 1971, 2099) if found else None


def jpeg_date(data: bytes):
    """Walk the JPEG markers to the first APP1 Exif segment before SOS."""
    at = 2
    while at + 4 <= len(data) and data[at] == 0xFF:
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
        if length < 2:
            return None
        segment = data[at + 4 : at + 2 + length]
        if marker == 0xE1 and segment[:6] == b"Exif\0\0":
            return exif_original(segment)
        at += 2 + length
    return None


def png_date(data: bytes):
    chunks = []
    at = 8
    while at + 12 <= len(data):
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
            text = body.split(b"\0", 1)[1].decode("latin-1") if b"\0" in body else ""
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
    while at + 8 <= len(data):
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
    found = list(re.finditer(rb"/CreationDate\s*\(", data))
    if not found:
        return None
    value = data[found[-1].end() : found[-1].end() + 64].split(b")")[0].decode("latin-1")
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
        at = start
        while at + 8 <= end:
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
        at = start
        while at + 8 <= end:
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
        exif_ids, places, idat = [], {}, None
        for kind, start, end in children(meta[0] + 4, meta[1]):
            if kind == b"iinf":
                width = 2 if data[start] == 0 else 4
                for entry, body, _body_end in children(start + 4 + width, end):
                    if entry == b"infe" and data[body] >= 2:
                        id_width = 2 if data[body] == 2 else 4
                        if data[body + 4 + id_width + 2 : body + 4 + id_width + 6] == b"Exif":
                            exif_ids.append(read(body + 4, id_width))
            elif kind == b"iloc":
                version = data[start]
                offset_size, length_size = data[start + 4] >> 4, data[start + 4] & 0x0F
                base_size = data[start + 5] >> 4
                index_size = data[start + 5] & 0x0F if version in (1, 2) else 0
                id_width = 4 if version == 2 else 2
                at = start + 6
                count = read(at, id_width)
                at += id_width
                for _ in range(count):
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
                    spans = []
                    for _ in range(extents):
                        at += index_size
                        offset = read(at, offset_size)
                        at += offset_size
                        length = read(at, length_size)
                        at += length_size
                        spans.append((offset, length))
                    places[item] = (method, base, spans)
            elif kind == b"idat":
                idat = start
        if not exif_ids or exif_ids[0] not in places:
            return None
        method, base, spans = places[exif_ids[0]]
        if method == 1 and idat is None or method not in (0, 1):
            return None
        origin = base + (idat if method == 1 else 0)
        payload = b"".join(data[origin + offset : origin + offset + length] if length else data[origin + offset :] for offset, length in spans)
        (skip,) = struct.unpack(">I", payload[:4])
        tiff = payload[4 + skip :]
        if tiff[:6] == b"Exif\0\0":
            tiff = tiff[6:]
        return exif_original(tiff) if tiff[:4] in (b"II*\0", b"MM\0*") else None
    except (IndexError, struct.error):
        return None


def searched_date(data: bytes):
    found = re.search(rb"Exif\x00\x00(?=II\*\x00|MM\x00\*)", data[:FOUR_MIB])
    return exif_original(data[found.start() :]) if found else None


def front_matter_date(text: str):
    lines = lines_of(text)
    if not lines or lines[0] != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            return None
        if line.startswith("date:"):
            value = line[len("date:") :].strip(" \t").strip("'\"")
            found = re.match(r"([0-9]{4})-([0-9]{2})-([0-9]{2})", value)
            return calendar(*map(int, found.groups()), 1971, 2099) if found else None
    return None


def embedded_date(kind: str, ext: str, data: bytes):
    if kind == "jpg":
        return jpeg_date(data)
    if kind == "tiff" or (kind == "raw" and data[:4] in (b"II*\0", b"MM\0*")):
        return exif_original(data)
    if kind in ("heic", "avif"):
        return heif_item_date(data)
    if kind == "raw" and ext == "cr3":
        return searched_date(data)
    if kind == "webp":
        return webp_date(data)
    if kind == "png":
        return png_date(data)
    if kind == "pdf":
        return pdf_date(data)
    if kind in ("docx", "xlsx", "pptx"):
        return xml_date(data, "docProps/core.xml", "dcterms:created")
    if kind in ("odt", "ods", "odp"):
        return xml_date(data, "meta.xml", "meta:creation-date")
    if kind in ("mp4", "mov", "m4a"):
        return media_date(data)
    if kind == "md":
        text = as_text(data)
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
    date = embedded_date(kind, ext, data) or named
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


def survey_folder(root: str):
    """(files that take part, every existing path) under `root`, by RULES §1, with os.walk."""
    files, paths = [], []
    for here, folders, names in os.walk(root):
        relative = os.path.relpath(here, root)
        prefix = "" if relative == "." else relative.replace(os.sep, "/") + "/"
        for folder in list(folders):
            paths.append(prefix + folder)
            if hidden(folder) or os.path.islink(os.path.join(here, folder)):
                folders.remove(folder)
        for name in names:
            paths.append(prefix + name)
            if not hidden(name) and os.path.isfile(os.path.join(here, name)) and not os.path.islink(os.path.join(here, name)):
                files.append(prefix + name)
    return sorted(files), sorted(paths)


def organize(root: str) -> dict:
    """The rules applied to the folder at `root`: every file's facts, in order, and every step."""
    files, paths = survey_folder(root)
    found = [facts(path, open(os.path.join(root, path), "rb").read()) for path in files]  # noqa: SIM115
    order = sorted(found, key=lambda item: (0 if item["conforming"] else 1, item["path"]))
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
