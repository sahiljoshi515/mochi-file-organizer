"""Valid sample files of every type RULES.md knows, built in memory, deterministically, with a chosen
embedded date (or none). Test infrastructure only: Pillow is a dev dependency.

Each builder returns bytes; `SAMPLES` maps a type to a builder `(seed, date) -> bytes`, where `date` is
`YYYY-MM-DD` or None and the seed varies the content so different seeds give different bytes.
"""

from __future__ import annotations

import datetime
import gzip
import io
import json
import random
import struct
import tarfile
import wave
import zipfile

from PIL import Image

EXIF_TIME = "12:34:56"
ZIP_DATE = (2020, 1, 2, 3, 4, 6)


def exif_bytes(date: str | None) -> bytes:
    """A TIFF/EXIF block (with the `Exif\\0\\0` header) holding DateTimeOriginal, or a camera make only."""
    exif = Image.Exif()
    exif[0x010F] = "TestCam"
    if date:
        exif.get_ifd(0x8769)[0x9003] = f"{date.replace('-', ':')} {EXIF_TIME}"
    return exif.tobytes()


def picture(seed: int, size: int = 16) -> Image.Image:
    rng = random.Random(f"picture:{seed}")
    image = Image.new("RGB", (size, size), tuple(rng.randrange(256) for _ in range(3)))
    for _ in range(6):
        image.putpixel((rng.randrange(size), rng.randrange(size)), tuple(rng.randrange(256) for _ in range(3)))
    return image


def saved(image: Image.Image, fmt: str, **options) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, fmt, **options)
    return buffer.getvalue()


def jpeg(seed: int, date: str | None) -> bytes:
    return saved(picture(seed), "JPEG", exif=exif_bytes(date), quality=85)


def tiff(seed: int, date: str | None) -> bytes:
    return saved(picture(seed), "TIFF", exif=exif_bytes(date))


def webp(seed: int, date: str | None) -> bytes:
    return saved(picture(seed), "WEBP", exif=exif_bytes(date), lossless=True)


def png(seed: int, date: str | None) -> bytes:
    return saved(picture(seed), "PNG", exif=exif_bytes(date))


def png_text(seed: int, date: str | None, rfc: bool = False) -> bytes:
    """A PNG whose date is a tEXt `Creation Time` (ISO, or RFC 1123 with rfc=True), no eXIf."""
    from PIL.PngImagePlugin import PngInfo

    info = PngInfo()
    if date:
        if rfc:
            year, month, day = date.split("-")
            month_name = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][int(month) - 1]
            info.add_text("Creation Time", f"Mon, {int(day):02d} {month_name} {year} 10:00:00 +0000")
        else:
            info.add_text("Creation Time", f"{date}T10:00:00")
    info.add_text("Comment", f"sample {seed}")
    return saved(picture(seed), "PNG", pnginfo=info)


def gif(seed: int, date: str | None) -> bytes:
    return saved(picture(seed).convert("P"), "GIF")


def avif(seed: int, date: str | None) -> bytes:
    return saved(picture(seed, 32), "AVIF", exif=exif_bytes(date), quality=50)


def box(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", 8 + len(body)) + kind + body


def full_box(kind: bytes, version: int, flags: int, body: bytes) -> bytes:
    return box(kind, bytes([version]) + flags.to_bytes(3, "big") + body)


def heif(seed: int, date: str | None, major: bytes = b"heic", compatible: tuple[bytes, ...] = (b"mif1", b"heic")) -> bytes:
    """A small, structurally valid HEIF: ftyp, meta (hdlr pict, pitm, iinf with an Exif item, iloc), mdat.
    The Exif item is `<offset 6>Exif\\0\\0<TIFF>`, as iPhones store it."""
    payload = struct.pack(">I", 6) + exif_bytes(date) + bytes(random.Random(f"heif:{seed}").randrange(256) for _ in range(32))
    ftyp = box(b"ftyp", major + b"\x00\x00\x00\x00" + b"".join(compatible))
    hdlr = full_box(b"hdlr", 0, 0, b"\x00\x00\x00\x00pict" + b"\x00" * 12 + b"\x00")
    pitm = full_box(b"pitm", 0, 0, struct.pack(">H", 1))
    infe = full_box(b"infe", 2, 0, struct.pack(">HH", 1, 0) + b"Exif" + b"\x00")
    iinf = full_box(b"iinf", 0, 0, struct.pack(">H", 1) + infe)

    def meta_with(offset: int) -> bytes:
        # iloc version 0: offset_size 4, length_size 4, base_offset_size 0; one item, one extent
        iloc = full_box(b"iloc", 0, 0, bytes([0x44, 0x00]) + struct.pack(">HHHH", 1, 1, 0, 1) + struct.pack(">II", offset, len(payload)))
        return full_box(b"meta", 0, 0, hdlr + pitm + iinf + iloc)

    head = ftyp + meta_with(0)
    offset = len(head) + 8
    return ftyp + meta_with(offset) + box(b"mdat", payload)


def iso_media(seed: int, date: str | None, major: bytes = b"isom", compatible: tuple[bytes, ...] = (b"isom", b"mp42")) -> bytes:
    """ftyp + moov(mvhd version 0 with the creation time of `date` at noon UTC, or 0) + mdat."""
    seconds = 0
    if date:
        year, month, day = (int(part) for part in date.split("-"))
        days = (datetime.date(year, month, day) - datetime.date(1904, 1, 1)).days
        seconds = days * 86400 + 12 * 3600
    mvhd = full_box(b"mvhd", 0, 0, struct.pack(">IIII", seconds, seconds, 1000, 1000) + b"\x00\x01\x00\x00\x01\x00" + b"\x00" * 70 + struct.pack(">I", 2))
    rng = random.Random(f"media:{seed}")
    return box(b"ftyp", major + b"\x00\x00\x02\x00" + b"".join(compatible)) + box(b"moov", mvhd) + box(b"mdat", bytes(rng.randrange(256) for _ in range(64)))


def mp4(seed: int, date: str | None) -> bytes:
    return iso_media(seed, date)


def mov(seed: int, date: str | None) -> bytes:
    return iso_media(seed, date, b"qt  ", (b"qt  ",))


def m4a(seed: int, date: str | None) -> bytes:
    return iso_media(seed, date, b"M4A ", (b"M4A ", b"mp42", b"isom"))


def pdf(seed: int, date: str | None, updated: str | None = None) -> bytes:
    """A small PDF whose Info dictionary holds /CreationDate; `updated` appends an incremental update with a later one."""
    lines = [b"%PDF-1.4", b"%\xe2\xe3\xcf\xd3"]
    lines.append(b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj")
    lines.append(b"2 0 obj << /Type /Pages /Kids [] /Count 0 >> endobj")
    info = f"3 0 obj << /Producer (builder {seed})" + (f" /CreationDate (D:{date.replace('-', '')}101500+02'00')" if date else "") + " >> endobj"
    lines.append(info.encode())
    lines += [b"trailer << /Root 1 0 R /Info 3 0 R >>", b"%%EOF"]
    if updated:
        lines += [f"3 0 obj << /CreationDate (D:{updated.replace('-', '')}080000Z) >> endobj".encode(), b"trailer << /Root 1 0 R /Info 3 0 R >>", b"%%EOF"]
    return b"\n".join(lines) + b"\n"


def zipped(entries: list[tuple[str, bytes, int]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data, method in entries:
            info = zipfile.ZipInfo(name, ZIP_DATE)
            info.compress_type = method
            archive.writestr(info, data)
    return buffer.getvalue()


def core_xml(date: str | None) -> bytes:
    created = f'<dcterms:created xsi:type="dcterms:W3CDTF">{date}T09:30:00Z</dcterms:created>' if date else ""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties'
        ' xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"'
        ' xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<dc:creator>builder</dc:creator>{created}</cp:coreProperties>"
    ).encode()


OOXML_MAIN = {"docx": "word/document.xml", "xlsx": "xl/workbook.xml", "pptx": "ppt/presentation.xml"}


def ooxml(kind: str, seed: int, date: str | None, deflate: bool = True) -> bytes:
    method = zipfile.ZIP_DEFLATED if deflate else zipfile.ZIP_STORED
    return zipped(
        [
            ("[Content_Types].xml", b'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>', method),
            ("_rels/.rels", b'<?xml version="1.0"?><Relationships/>', method),
            (OOXML_MAIN[kind], f"<doc>sample {seed} {'lorem ' * (seed % 7 + 3)}</doc>".encode(), method),
            ("docProps/core.xml", core_xml(date), method),
        ]
    )


ODF_MIMES = {
    "odt": b"application/vnd.oasis.opendocument.text",
    "ods": b"application/vnd.oasis.opendocument.spreadsheet",
    "odp": b"application/vnd.oasis.opendocument.presentation",
}


def odf(kind: str, seed: int, date: str | None, deflate: bool = True) -> bytes:
    method = zipfile.ZIP_DEFLATED if deflate else zipfile.ZIP_STORED
    meta = (
        '<?xml version="1.0" encoding="UTF-8"?><office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"'
        ' xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0"><office:meta>'
        + (f"<meta:creation-date>{date}T08:00:00</meta:creation-date>" if date else "")
        + "</office:meta></office:document-meta>"
    ).encode()
    return zipped(
        [
            ("mimetype", ODF_MIMES[kind], zipfile.ZIP_STORED),
            ("META-INF/manifest.xml", b"<manifest/>", method),
            ("content.xml", f"<content>sample {seed}</content>".encode(), method),
            ("meta.xml", meta, method),
        ]
    )


def epub(seed: int, date: str | None) -> bytes:
    return zipped(
        [
            ("mimetype", b"application/epub+zip", zipfile.ZIP_STORED),
            ("META-INF/container.xml", b"<container/>", zipfile.ZIP_DEFLATED),
            ("content.opf", f"<package>book {seed}</package>".encode(), zipfile.ZIP_DEFLATED),
        ]
    )


def plain_zip(seed: int, date: str | None) -> bytes:
    return zipped([(f"file{index}.txt", f"entry {seed}.{index}\n".encode(), zipfile.ZIP_DEFLATED) for index in range(3)])


def jar(seed: int, date: str | None) -> bytes:
    return zipped([("META-INF/MANIFEST.MF", f"Manifest-Version: 1.0\nBuild: {seed}\n".encode(), zipfile.ZIP_DEFLATED)])


def wav(seed: int, date: str | None) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as sound:
        sound.setnchannels(1)
        sound.setsampwidth(1)
        sound.setframerate(8000)
        sound.writeframes(bytes(random.Random(f"wav:{seed}").randrange(256) for _ in range(200)))
    return buffer.getvalue()


def avi(seed: int, date: str | None) -> bytes:
    body = b"AVI " + b"LIST" + struct.pack("<I", 12) + b"hdrl" + bytes([seed % 256] * 8)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def mp3(seed: int, date: str | None) -> bytes:
    rng = random.Random(f"mp3:{seed}")
    frame = b"\xff\xfb\x90\x64" + bytes(rng.randrange(256) for _ in range(413))
    if seed % 2:
        return b"ID3\x03\x00\x00\x00\x00\x00\x0a" + b"TIT2\x00\x00\x00\x00\x00\x00"[:10] + frame
    return frame * 2


def flac(seed: int, date: str | None) -> bytes:
    return b"fLaC" + b"\x80\x00\x00\x22" + bytes(random.Random(f"flac:{seed}").randrange(256) for _ in range(34))


def ogg(seed: int, date: str | None) -> bytes:
    return b"OggS\x00\x02" + bytes(random.Random(f"ogg:{seed}").randrange(256) for _ in range(40))


def ebml(seed: int, date: str | None, doctype: bytes = b"webm") -> bytes:
    header = b"\x42\x82" + bytes([0x80 | len(doctype)]) + doctype
    return b"\x1a\x45\xdf\xa3" + bytes([0x80 | len(header)]) + header + bytes(random.Random(f"ebml:{seed}").randrange(256) for _ in range(40))


def webm(seed: int, date: str | None) -> bytes:
    return ebml(seed, date, b"webm")


def mkv(seed: int, date: str | None) -> bytes:
    return ebml(seed, date, b"matroska")


def gz(seed: int, date: str | None) -> bytes:
    return gzip.compress(f"log line {seed}\n".encode() * 20, mtime=0)


def tar(seed: int, date: str | None) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        data = f"member {seed}\n".encode()
        info = tarfile.TarInfo(f"member{seed}.txt")
        info.size, info.mtime = len(data), 1_600_000_000
        archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def sevenzip(seed: int, date: str | None) -> bytes:
    return b"7z\xbc\xaf\x27\x1c\x00\x04" + bytes(random.Random(f"7z:{seed}").randrange(256) for _ in range(32))


def rar(seed: int, date: str | None) -> bytes:
    return b"Rar!\x1a\x07\x01\x00" + bytes(random.Random(f"rar:{seed}").randrange(256) for _ in range(32))


def raw_nef(seed: int, date: str | None) -> bytes:
    """A TIFF-structured raw file (claimed .nef keeps it raw)."""
    return tiff(seed, date)


def raf(seed: int, date: str | None) -> bytes:
    return b"FUJIFILMCCD-RAW 0201FF383501" + bytes(random.Random(f"raf:{seed}").randrange(256) for _ in range(40))


def blob(seed: int, date: str | None) -> bytes:
    rng = random.Random(f"blob:{seed}")
    return b"\x00\x01BLOB" + bytes(rng.randrange(256) for _ in range(48 + seed % 30))


WORDS = ["alpha", "budget", "contract", "draft", "export", "family", "garden", "holiday", "invoice", "journal", "kitchen", "lecture", "meeting", "notes", "offer", "plan"]


def words(seed: int, count: int) -> str:
    rng = random.Random(f"words:{seed}")
    return " ".join(rng.choice(WORDS) for _ in range(count))


def text_txt(seed: int, date: str | None) -> bytes:
    return f"{words(seed, 12)}\n{words(seed + 1, 9)}\n".encode()


def text_md(seed: int, date: str | None) -> bytes:
    front = f"---\ntitle: Note {seed}\ndate: {date}\n---\n" if date else ""
    return f"{front}# {words(seed, 3).title()}\n\n{words(seed, 20)}\n".encode()


def text_csv(seed: int, date: str | None) -> bytes:
    rng = random.Random(f"csv:{seed}")
    return ("name,amount,city\n" + "".join(f"{rng.choice(WORDS)},{rng.randrange(1000)},{rng.choice(WORDS)}\n" for _ in range(4))).encode()


def text_json(seed: int, date: str | None) -> bytes:
    return json.dumps({"id": seed, "tags": words(seed, 3).split(), "ok": True}, indent=2).encode()


def text_log(seed: int, date: str | None) -> bytes:
    day = date or "2021-05-06"
    return "".join(f"{day} 10:0{index}:00 INFO {words(seed + index, 4)}\n" for index in range(3)).encode()


def text_html(seed: int, date: str | None) -> bytes:
    return f"<!DOCTYPE html>\n<html><head><title>Page {seed}</title></head><body><p>{words(seed, 8)}</p></body></html>\n".encode()


def text_svg(seed: int, date: str | None) -> bytes:
    return f'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="{seed % 9 + 1}" height="3"/></svg>\n'.encode()


def text_py(seed: int, date: str | None) -> bytes:
    return f"def value():\n    return {seed}\n\n\nprint(value())\n".encode()


def text_yaml(seed: int, date: str | None) -> bytes:
    return f"name: sample-{seed}\nitems:\n  - {words(seed, 1)}\n".encode()


def text_rtf(seed: int, date: str | None) -> bytes:
    return f"{{\\rtf1\\ansi {words(seed, 6)}}}\n".encode()


SAMPLES = {
    "jpg": jpeg, "tiff": tiff, "webp": webp, "png": png, "png-text": png_text, "gif": gif, "avif": avif,
    "heic": heif, "mp4": mp4, "mov": mov, "m4a": m4a, "pdf": pdf, "docx": lambda s, d: ooxml("docx", s, d),
    "xlsx": lambda s, d: ooxml("xlsx", s, d, deflate=False), "pptx": lambda s, d: ooxml("pptx", s, d),
    "odt": lambda s, d: odf("odt", s, d), "ods": lambda s, d: odf("ods", s, d, deflate=False), "odp": lambda s, d: odf("odp", s, d),
    "epub": epub, "zip": plain_zip, "jar": jar, "wav": wav, "avi": avi, "mp3": mp3, "flac": flac, "ogg": ogg,
    "webm": webm, "mkv": mkv, "gz": gz, "tar": tar, "7z": sevenzip, "rar": rar, "nef": raw_nef, "raf": raf, "bin": blob,
    "txt": text_txt, "md": text_md, "csv": text_csv, "json": text_json, "log": text_log, "html": text_html,
    "svg": text_svg, "py": text_py, "yaml": text_yaml, "rtf": text_rtf,
}  # fmt: skip
# The extension a well-named sample carries, and whether its type can hold an embedded date.
NATURAL_EXT = {"png-text": "png", "heic": "heic", "nef": "nef", "raf": "raf", "7z": "7z", "bin": "dat"}
DATED = frozenset({"jpg", "tiff", "webp", "png", "png-text", "avif", "heic", "mp4", "mov", "m4a", "pdf", "docx", "xlsx", "pptx", "odt", "ods", "odp", "md", "nef"})


def natural_ext(kind: str) -> str:
    return NATURAL_EXT.get(kind, kind)
