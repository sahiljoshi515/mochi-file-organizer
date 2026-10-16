"""RULES.md §2: a file's group, type and extension, decided by its content (and, for text, its claimed
extension). Shared, byte for byte, by src/plugin/ and verifier/.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .formats import zip_entries, zip_read

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
TEXT_ALIASES = {"markdown": "md", "yml": "yaml", "htm": "html", "ndjson": "jsonl"}
# Extensions the binary table gives, and the aliases it never keeps: a file that does not match their
# content never keeps one as other/<ext>.
TABLE_EXTS = frozenset(
    ["pdf", "png", "jpg", "gif", "webp", "wav", "avi", "heic", "avif", "mov", "m4a", "cr3", "mp4", "tiff", "raf", "mp3", "flac", "ogg", "webm", "mkv", "docx", "xlsx", "pptx", "odt", "ods", "odp", "epub", "zip", "gz", "tar", "7z", "rar", "jpeg", "jpe", "jfif", "tif"]
)
HEIC_BRANDS = frozenset({b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"})
AVIF_BRANDS = frozenset({b"avif", b"avis"})
ODF_TYPES = {
    b"application/vnd.oasis.opendocument.text": ("documents", "odt"),
    b"application/vnd.oasis.opendocument.spreadsheet": ("spreadsheets", "ods"),
    b"application/vnd.oasis.opendocument.presentation": ("presentations", "odp"),
    b"application/epub+zip": ("documents", "epub"),
}
OOXML_PARTS = (("word/document.xml", "documents", "docx"), ("xl/workbook.xml", "spreadsheets", "xlsx"), ("ppt/presentation.xml", "presentations", "pptx"))
LOG_FIRST = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2}")
BOM = b"\xef\xbb\xbf"


@dataclass(frozen=True)
class Kind:
    group: str
    type: str
    ext: str

    @property
    def folder(self) -> str:
        return f"{self.group}/{self.type}"


def decoded(data: bytes) -> str | None:
    """`data` as UTF-8 text without its BOM, or None when it does not decode or holds a NUL byte."""
    try:
        text = (data.removeprefix(BOM)).decode("utf-8")
    except UnicodeDecodeError:
        return None
    return None if "\x00" in text else text


def mpeg_frame(data: bytes) -> bool:
    if len(data) < 3 or data[0] != 0xFF or data[1] & 0xE0 != 0xE0:
        return False
    return (data[1] >> 3) & 3 != 1 and (data[1] >> 1) & 3 != 0 and data[2] >> 4 != 15 and (data[2] >> 2) & 3 != 3


def iso_kind(data: bytes) -> Kind:
    size = int.from_bytes(data[0:4], "big")
    major = data[8:12]
    end = min(len(data), size) if size >= 16 else 16
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
    """Rule: a claimed extension that is neither a text extension nor one the table gives is kept as other/<ext>."""
    if claimed and claimed not in TEXT_GROUPS and claimed not in TEXT_ALIASES and claimed not in TABLE_EXTS:
        return Kind("other", claimed, claimed)
    return Kind("other", "bin", "bin")


def zip_kind(data: bytes, claimed: str) -> Kind:
    entries = zip_entries(data)
    names = {entry.name for entry in entries}
    for part, group, kind in OOXML_PARTS:
        if part in names:
            return Kind(group, kind, kind)
    for entry in entries:
        if entry.name == "mimetype":
            content = zip_read(data, entry)
            if content in ODF_TYPES:
                group, kind = ODF_TYPES[content]
                return Kind(group, kind, kind)
            break
    if claimed and claimed not in TEXT_GROUPS and claimed not in TEXT_ALIASES and claimed not in TABLE_EXTS:
        return Kind("other", claimed, claimed)
    return Kind("archives", "zip", "zip")


def is_json(text: str) -> bool:
    try:
        json.loads(text)
    except (ValueError, RecursionError):
        return False
    return True


def is_csv(text: str) -> bool:
    lines = [line for line in (line.rstrip("\r") for line in text.split("\n")) if line.strip()]
    counts = {line.count(",") for line in lines}
    return len(lines) >= 3 and len(counts) == 1 and min(counts) >= 1


def svg_after_declaration(head: str) -> bool:
    """Whether `<svg` follows the first `?>` (within the first 4,096 characters) after optional whitespace."""
    end = head.find("?>", 0, 4096)
    return end >= 0 and end + 2 <= 4096 and head[end + 2 :].lstrip().startswith("<svg")


def text_kind(text: str, claimed: str) -> Kind:
    ext = TEXT_ALIASES.get(claimed, claimed)
    if ext in TEXT_GROUPS:
        return Kind(TEXT_GROUPS[ext], ext, ext)
    head = text.lstrip()
    first = text.split("\n", 1)[0].rstrip("\r")
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
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return Kind("images", "raw", claimed) if claimed in RAW_EXTS else Kind("images", "tiff", "tiff")
    if data.startswith(b"FUJIFILMCCD-RAW"):
        return Kind("images", "raw", "raf")
    if (data.startswith(b"ID3") and len(data) > 3 and data[3] in (2, 3, 4)) or mpeg_frame(data):
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
    return other(claimed)
