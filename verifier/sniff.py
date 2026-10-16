"""RULES.md §2: a file's group, type and extension, decided by its content (and, for text, its claimed
extension). Shared, byte for byte, by src/plugin/ and verifier/.
"""

from __future__ import annotations

import itertools
import json
import re
from dataclasses import dataclass

from .formats import FRONT_LINES, number, zip_entry, zip_member, zip_read

RAW_EXTS = frozenset(["dng", "nef", "cr2", "arw", "orf", "rw2", "pef", "srw", "nrw", "3fr", "erf", "kdc", "mos", "mef", "iiq"])
TEXT_GROUPS = {
    **dict.fromkeys(["txt", "md", "rst", "tex", "org", "rtf", "html"], "documents"),
    "svg": "images",
    **dict.fromkeys(["csv", "tsv"], "spreadsheets"),
    **dict.fromkeys(["json", "jsonl", "geojson", "ipynb", "xml", "yaml", "toml", "ini", "cfg", "conf", "sql", "log", "srt", "vtt", "ics", "vcf", "bib"], "data"),
    **dict.fromkeys(
        ["py", "js", "mjs", "cjs", "ts", "tsx", "jsx", "c", "h", "cc", "cpp", "hpp", "cs", "java", "kt", "go", "rs", "rb", "php", "swift", "scala", "lua", "pl", "r", "sh", "bash", "zsh", "fish", "ps1", "bat", "css", "scss", "less", "vue", "svelte", "dart", "proto"],
        "code",
    ),
}
NORMALIZED = {"markdown": "md", "yml": "yaml", "htm": "html", "ndjson": "jsonl", "jpeg": "jpg", "jpe": "jpg", "jfif": "jpg", "tif": "tiff"}
# Office main parts and the extension each content type of theirs gives (RULES §2, zips).
WORD_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml": "docx",
    "application/vnd.ms-word.document.macroenabled.main+xml": "docm",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml": "dotx",
    "application/vnd.ms-word.template.macroenabledtemplate.main+xml": "dotm",
}
EXCEL_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml": "xlsx",
    "application/vnd.ms-excel.sheet.macroenabled.main+xml": "xlsm",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.template.main+xml": "xltx",
    "application/vnd.ms-excel.template.macroenabled.main+xml": "xltm",
    "application/vnd.ms-excel.addin.macroenabled.main+xml": "xlam",
    "application/vnd.ms-excel.sheet.binary.macroenabled.main": "xlsb",
}
POWERPOINT_TYPES = {
    "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml": "pptx",
    "application/vnd.ms-powerpoint.presentation.macroenabled.main+xml": "pptm",
    "application/vnd.openxmlformats-officedocument.presentationml.template.main+xml": "potx",
    "application/vnd.ms-powerpoint.template.macroenabled.main+xml": "potm",
    "application/vnd.openxmlformats-officedocument.presentationml.slideshow.main+xml": "ppsx",
    "application/vnd.ms-powerpoint.slideshow.macroenabled.main+xml": "ppsm",
    "application/vnd.ms-powerpoint.addin.macroenabled.main+xml": "ppam",
}
OFFICE = (
    (("word/document.xml",), "documents", "docx", WORD_TYPES),
    (("xl/workbook.xml", "xl/workbook.bin"), "spreadsheets", "xlsx", EXCEL_TYPES),
    (("ppt/presentation.xml",), "presentations", "pptx", POWERPOINT_TYPES),
)
OFFICE_EXTS = frozenset(ext for _parts, _group, _plain, types in OFFICE for ext in types.values())
# Extensions the binary table gives, and the aliases it never keeps: a file that does not match their
# content never keeps one as other/<ext>.
TABLE_EXTS = frozenset(
    ["pdf", "png", "jpg", "gif", "webp", "wav", "avi", "heic", "avif", "mov", "m4a", "cr3", "mp4", "tiff", "raf", "mp3", "flac", "ogg", "webm", "mkv", "zip", "gz", "tar", "7z", "rar", "ts", "epub", "odt", "ods", "odp", "jpeg", "jpe", "jfif", "tif", *OFFICE_EXTS]
)
HEIC_BRANDS = frozenset({b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"})
AVIF_BRANDS = frozenset({b"avif", b"avis"})
QUICKTIME_ATOMS = frozenset({b"moov", b"mdat", b"wide", b"free", b"skip", b"pnot"})
ODF_TYPES = {
    b"application/vnd.oasis.opendocument.text": ("documents", "odt"),
    b"application/vnd.oasis.opendocument.spreadsheet": ("spreadsheets", "ods"),
    b"application/vnd.oasis.opendocument.presentation": ("presentations", "odp"),
    b"application/epub+zip": ("documents", "epub"),
}
CONTENT_TAG = re.compile(r"<(Override|Default)\b([^<>]*+)>")
CONTENT_ATTRIBUTE = re.compile(r"""\b(PartName|Extension|ContentType)\s*=\s*("[^"]*"|'[^']*')""")
LOG_FIRST = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2}")
BOM = b"\xef\xbb\xbf"
# Only codecs Python decodes without importing a codec module, which a verifier may not do: "utf-16"
# and "utf-32" read the byte-order mark (and drop it); Windows-1252 is Latin-1 with bytes 80-9F mapped.
WIDE_BOMS = ((b"\xff\xfe\x00\x00", "utf-32"), (b"\x00\x00\xfe\xff", "utf-32"), (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16"))
CP1252_HIGH = (
    "\u20ac\x81\u201a\u0192\u201e\u2026\u2020\u2021\u02c6\u2030\u0160\u2039\u0152\x8d\u017d\x8f"
    "\x90\u2018\u2019\u201c\u201d\u2022\u2013\u2014\u02dc\u2122\u0161\u203a\u0153\x9d\u017e\u0178"
)
CP1252 = {0x80 + index: char for index, char in enumerate(CP1252_HIGH)}
# Bytes that keep a file from being Windows-1252 text: NUL and the other control characters but tab,
# line feed, form feed and carriage return, and the five bytes Windows-1252 leaves undefined.
LEGACY_REFUSED = re.compile(rb"[\x00-\x08\x0b\x0e-\x1f\x7f\x81\x8d\x8f\x90\x9d]")
CSV_LINES = 1000
# A JSON string, or an unterminated one running to the end: possessive, so stripping strings is linear.
JSON_STRING = re.compile(r'"(?:[^"\\]|\\(?:.|\Z))*+(?:"|\Z)', re.DOTALL)
NOT_BRACKET = re.compile(r"[^\[\]{}]+")
BRACKET_STEP = {"[": 1, "{": 1, "]": -1, "}": -1}
JSON_DEPTH = 512
# MPEG audio: kbit/s for bitrate indexes 1-14, by (MPEG-1?, layer); sample rates by version bits.
BITRATES = {
    (True, 1): (32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448),
    (True, 2): (32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384),
    (True, 3): (32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
    (False, 1): (32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256),
    (False, 2): (8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
    (False, 3): (8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
}
SAMPLE_RATES = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}
BRANDS = 1024  # an ftyp box is read for its first 1,024 compatible brands
TS_PACKET = 188
TS_PACKETS = 20


@dataclass(frozen=True)
class Kind:
    group: str
    type: str
    ext: str

    @property
    def folder(self) -> str:
        return f"{self.group}/{self.type}"


def normalized(claimed: str) -> str:
    return NORMALIZED.get(claimed, claimed)


def kept_ext(claimed: str) -> bool:
    """Whether a claimed extension is kept as other/<ext>: neither a text extension nor one the table gives."""
    return bool(claimed) and normalized(claimed) not in TEXT_GROUPS and claimed not in TABLE_EXTS


# ----- Text (rows 10, 19 and 20) -----


def wide_text(data: bytes) -> str | None:
    """Row 10: text after a UTF-32 or UTF-16 byte-order mark, or None."""
    for bom, codec in WIDE_BOMS:
        if data.startswith(bom):
            try:
                text = data.decode(codec)
            except UnicodeDecodeError:
                return None
            return None if "\x00" in text else text
    return None


def decoded(data: bytes) -> str | None:
    """Row 19: `data` as UTF-8 text without its BOM, or None when it does not decode or holds a NUL."""
    try:
        text = data.removeprefix(BOM).decode("utf-8")
    except UnicodeDecodeError:
        return None
    return None if "\x00" in text else text


def legacy(data: bytes, claimed: str) -> bool:
    """Row 20: whether `data` is Windows-1252 text in a file that claims a text extension. Its content
    is never needed to type it (the claimed extension decides), so the bytes alone are checked."""
    return normalized(claimed) in TEXT_GROUPS and LEGACY_REFUSED.search(data) is None


def as_text(data: bytes, claimed: str) -> str | None:
    """The text a text row reads from `data` (rows 10, 19 and 20, in that order), or None; Windows-1252
    text only as far as its first 1,000 lines (the front matter's reach)."""
    text = wide_text(data)
    if text is None:
        text = decoded(data)
    if text is None and legacy(data, claimed):
        text = b"\n".join(data.split(b"\n", FRONT_LINES)[:FRONT_LINES]).decode("latin-1").translate(CP1252)
    return text


def json_depth(text: str) -> int:
    """How deep arrays and objects nest outside strings."""
    brackets = NOT_BRACKET.sub("", JSON_STRING.sub("", text))
    return max(itertools.accumulate(map(BRACKET_STEP.get, brackets)), default=0)


def not_a_constant(name: str) -> None:
    raise ValueError(f"{name} is not JSON")


def is_json(text: str) -> bool:
    """RFC 8259 JSON nested at most 512 deep (NaN and Infinity are not JSON). The parser runs first: a
    RecursionError (only ever far deeper than 512) or a parse error is "not JSON" either way, so the
    answer does not depend on the stack, and most text that is not JSON fails fast."""
    try:
        json.loads(text, parse_constant=not_a_constant, parse_int=str, parse_float=str)
    except (ValueError, RecursionError):
        return False
    return json_depth(text) <= JSON_DEPTH


def is_csv(text: str) -> bool:
    """Among the first 1,000 lines: at least 3 non-blank lines, all with the same number of commas, at least one."""
    count = None
    lines = 0
    for line in text.split("\n", CSV_LINES)[:CSV_LINES]:
        if not line.strip():
            continue
        commas = line.count(",")
        if count is not None and commas != count:
            return False
        count = commas
        lines += 1
    return lines >= 3 and count is not None and count >= 1


def svg_after_declaration(head: str) -> bool:
    """Whether `<svg` follows the first `?>` (within the first 4,096 characters) after optional whitespace."""
    end = head.find("?>", 0, 4096)
    return end >= 0 and end + 2 <= 4096 and head[end + 2 :].lstrip().startswith("<svg")


def text_kind(text: str, claimed: str) -> Kind:
    ext = normalized(claimed)
    if ext in TEXT_GROUPS:
        return Kind(TEXT_GROUPS[ext], ext, ext)
    if kept_ext(claimed):
        return Kind("other", claimed, claimed)
    head = text.lstrip()
    first = text.split("\n", 1)[0].removesuffix("\r")
    lower = head[:64].lower()
    if head.startswith("<svg") or (head.startswith("<?xml") and svg_after_declaration(head)):
        return Kind("images", "svg", "svg")
    if lower.startswith(("<!doctype html", "<html")):
        return Kind("documents", "html", "html")
    if head.startswith("{\\rtf"):
        return Kind("documents", "rtf", "rtf")
    if head.startswith(("{", "[")) and is_json(text):
        return Kind("data", "json", "json")
    if first.startswith("# ") or first == "---":
        return Kind("documents", "md", "md")
    if is_csv(text):
        return Kind("spreadsheets", "csv", "csv")
    if LOG_FIRST.match(first):
        return Kind("data", "log", "log")
    return Kind("documents", "txt", "txt")


# ----- Binary rows -----


def mpeg_header(data: bytes, at: int) -> tuple[int, int, int] | None:
    """(version bits, layer, frame length) of a valid MPEG audio frame header at `at`, or None."""
    if at + 4 > len(data) or data[at] != 0xFF or data[at + 1] & 0xE0 != 0xE0:
        return None
    version, layer_bits = (data[at + 1] >> 3) & 3, (data[at + 1] >> 1) & 3
    bitrate_index, rate_index, padding = data[at + 2] >> 4, (data[at + 2] >> 2) & 3, (data[at + 2] >> 1) & 1
    if version == 1 or layer_bits == 0 or bitrate_index in (0, 15) or rate_index == 3:
        return None
    layer = 4 - layer_bits
    bitrate = BITRATES[version == 3, layer][bitrate_index - 1] * 1000
    rate = SAMPLE_RATES[version][rate_index]
    if layer == 1:
        length = (12 * bitrate // rate + padding) * 4
    elif layer == 2 or version == 3:
        length = 144 * bitrate // rate + padding
    else:
        length = 72 * bitrate // rate + padding
    return version, layer, length


def mpeg_audio(data: bytes) -> bool:
    """A frame header at 0, and, when the file holds that frame and 4 bytes more, a second like it right after."""
    first = mpeg_header(data, 0)
    if first is None:
        return False
    version, layer, length = first
    if len(data) < length + 4:
        return True
    second = mpeg_header(data, length)
    return second is not None and second[:2] == (version, layer)


def quicktime(data: bytes) -> bool:
    """Row 7: a classic QuickTime top-level atom at 0 whose size fits the file."""
    if len(data) < 8 or data[4:8] not in QUICKTIME_ATOMS:
        return False
    size = number(data, 0, 4, True)
    if size == 1:
        large = number(data, 8, 8, True)
        return large is not None and 16 <= large <= len(data)
    return size == 0 or 8 <= size <= len(data)


def transport_stream(data: bytes) -> bool:
    """Row 21: at least 3 packets of 188 bytes, each of the first 20 the file holds starting 0x47."""
    packets = min(TS_PACKETS, len(data) // TS_PACKET)
    return packets >= 3 and all(data[TS_PACKET * index] == 0x47 for index in range(packets))


def iso_kind(data: bytes) -> Kind:
    size = int.from_bytes(data[0:4], "big")
    major = data[8:12]
    end = min(len(data), size, 16 + 4 * BRANDS) if size >= 16 else 16
    compatible = {data[at : at + 4] for at in range(16, end - 3, 4)}
    if major in AVIF_BRANDS or (major in (b"mif1", b"msf1") and compatible & AVIF_BRANDS):
        return Kind("images", "avif", "avif")
    if major in HEIC_BRANDS:
        return Kind("images", "heic", "heic")
    if major == b"qt  ":
        return Kind("video", "mov", "mov")
    if major in (b"M4A ", b"M4B "):
        return Kind("audio", "m4a", "m4a")
    if major == b"crx ":
        return Kind("images", "raw", "cr3")
    return Kind("video", "mp4", "mp4")


def other(claimed: str) -> Kind:
    """Row 22: a claimed extension that is neither a text extension nor one the table gives is kept as other/<ext>."""
    if kept_ext(claimed):
        return Kind("other", claimed, claimed)
    return Kind("other", "bin", "bin")


def content_type(data: bytes, part: str) -> str | None:
    """The content type `[Content_Types].xml` gives an Office main part: its Override, else the Default
    for its extension (part names and extensions compared ignoring case)."""
    content = zip_member(data, "[Content_Types].xml")
    if content is None:
        return None
    override = default = None
    extension = part.rpartition(".")[2].lower()
    for tag in CONTENT_TAG.finditer(content.decode("utf-8", "replace")):
        attributes = {name: value[1:-1] for name, value in CONTENT_ATTRIBUTE.findall(tag.group(2))}
        if tag.group(1) == "Override" and override is None and attributes.get("PartName", "").lower() == "/" + part.lower():
            override = attributes.get("ContentType")
        elif tag.group(1) == "Default" and default is None and attributes.get("Extension", "").lower() == extension:
            default = attributes.get("ContentType")
    return override if override is not None else default


def office_kind(data: bytes, claimed: str) -> Kind | None:
    for parts, group, plain, types in OFFICE:
        part = next((part for part in parts if zip_entry(data, part) is not None), None)
        if part is None:
            continue
        found = content_type(data, part)
        ext = types.get(found.lower()) if found is not None else None
        if ext is None:
            ext = claimed if claimed in types.values() else plain
        return Kind(group, ext, ext)
    return None


def zip_kind(data: bytes, claimed: str) -> Kind:
    office = office_kind(data, claimed)
    if office is not None:
        return office
    entry = zip_entry(data, "mimetype")
    content = None if entry is None else zip_read(data, entry)
    if content in ODF_TYPES:
        group, kind = ODF_TYPES[content]
        return Kind(group, kind, kind)
    if kept_ext(claimed):
        return Kind("other", claimed, claimed)
    return Kind("archives", "zip", "zip")


def sniff(data: bytes, name: str, claimed: str) -> Kind:
    """RULES §2: the first row of the table whose content test `data` passes."""
    if data.startswith(b"%PDF-"):
        return Kind("documents", "pdf", "pdf")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return Kind("images", "png", "png")
    if data.startswith(b"\xff\xd8\xff"):
        return Kind("images", "jpg", "jpg")
    if data.startswith((b"GIF87a", b"GIF89a")):
        return Kind("images", "gif", "gif")
    if data.startswith(b"RIFF") and len(data) >= 12:
        form = data[8:12]
        if form == b"WEBP":
            return Kind("images", "webp", "webp")
        if form == b"WAVE":
            return Kind("audio", "wav", "wav")
        if form == b"AVI ":
            return Kind("video", "avi", "avi")
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return iso_kind(data)
    if quicktime(data):
        return Kind("video", "mov", "mov")
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return Kind("images", "raw", claimed) if claimed in RAW_EXTS else Kind("images", "tiff", "tiff")
    if data.startswith(b"FUJIFILMCCD-RAW"):
        return Kind("images", "raw", "raf")
    text = wide_text(data)
    if text is not None:
        return text_kind(text, claimed)
    if (data.startswith(b"ID3") and len(data) > 3 and data[3] in (2, 3, 4)) or mpeg_audio(data):
        return Kind("audio", "mp3", "mp3")
    if data.startswith(b"fLaC"):
        return Kind("audio", "flac", "flac")
    if data.startswith(b"OggS"):
        return Kind("audio", "ogg", "ogg")
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return Kind("video", "webm", "webm") if b"webm" in data[:64] else Kind("video", "mkv", "mkv")
    if data.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        return zip_kind(data, claimed)
    if data.startswith(b"\x1f\x8b"):
        lower = name.lower()
        return Kind("archives", "gz", "tar.gz" if lower.endswith((".tar.gz", ".tgz")) else "gz")
    if data[257:262] == b"ustar":
        return Kind("archives", "tar", "tar")
    if data.startswith(b"7z\xbc\xaf\x27\x1c"):
        return Kind("archives", "7z", "7z")
    if data.startswith(b"Rar!\x1a\x07"):
        return Kind("archives", "rar", "rar")
    text = decoded(data)
    if text is not None:
        return text_kind(text, claimed)
    if legacy(data, claimed):
        ext = normalized(claimed)
        return Kind(TEXT_GROUPS[ext], ext, ext)
    if transport_stream(data):
        return Kind("video", "ts", "ts")
    return other(claimed)
