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
import zlib

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

# ----- Edge files for the review's findings (FO-08 to FO-16) -----


def office_zip(main: str, content_type: str | None, default: str | None = None) -> bytes:
    types = ['<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">']
    if default:
        types.append(f'<Default Extension="{main.rsplit(".", 1)[1].upper()}" ContentType="{default}"/>')
    if content_type:
        types.append(f"<Override ContentType='{content_type}' PartName='/{main.upper()}'/>")
    types.append("</Types>")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "".join(types))
        archive.writestr(main, "<x/>")
        archive.writestr("docProps/core.xml", '<cp:coreProperties><dcterms:created xsi:type="x">2021-05-06T07:08:09Z</dcterms:created></cp:coreProperties>')
    return buffer.getvalue()


def tiff_ifd(tags: list[tuple[int, int, bytes]]) -> bytes:
    """A little-endian TIFF with one IFD at 8: (tag, type, value) entries; values over 4 bytes follow the IFD."""
    entries, extra = [], b""
    data_at = 8 + 2 + 12 * len(tags) + 4
    for tag, kind_code, value in tags:
        count = len(value) if kind_code == 2 else 1
        if len(value) <= 4:
            entries.append(struct.pack("<HHI", tag, kind_code, count) + value.ljust(4, b"\x00"))
        else:
            entries.append(struct.pack("<HHII", tag, kind_code, count, data_at + len(extra)))
            extra += value
    return b"II*\x00" + struct.pack("<I", 8) + struct.pack("<H", len(tags)) + b"".join(entries) + b"\x00\x00\x00\x00" + extra


def cr3(cmt1: bytes, cmt2: bytes | None) -> bytes:
    canon = bytes.fromhex("85c0b687820f11e08111f4ce462b6a48")
    parts = box(b"CMT1", cmt1) + (box(b"CMT2", cmt2) if cmt2 is not None else b"")
    moov = box(b"moov", box(b"uuid", canon + box(b"CNCV", b"CanonCR3_001/00.09.00/00.00.00") + parts))
    return box(b"ftyp", b"crx \x00\x00\x00\x01crx isom") + moov + box(b"mdat", b"\x00" * 16)


def png_with_text(text: str) -> bytes:
    import zlib

    def chunk(kind_name: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind_name + body + struct.pack(">I", zlib.crc32(kind_name + body))

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)) + chunk(b"tEXt", b"Creation Time\x00" + text.encode("latin-1")) + chunk(b"IEND", b"")


def classic_quicktime(seconds: int) -> bytes:
    """A QuickTime file without ftyp: moov (mvhd with `seconds` since 1904) first, then mdat."""
    mvhd = full_box(b"mvhd", 0, 0, struct.pack(">IIII", seconds, seconds, 600, 600) + b"\x00" * 80)
    return box(b"moov", mvhd) + box(b"mdat", b"\x00" * 32)


def transport_stream(packets: int) -> bytes:
    return b"".join(b"\x47" + bytes([index % 256]) * 187 for index in range(packets))


def edge_files() -> dict[str, bytes]:
    """Files at the edges RULES.md now decides: wide and legacy text, unlisted text extensions, the
    Office family, classic QuickTime, MPEG-TS, CR3 metadata, PDF information, JSON depth, zip end records."""
    note = "Notes from Tuesday\r\nbuy milk\r\n"
    canon_tiff = tiff_ifd([(0x010F, 2, b"Canon\x00")])
    document = office_zip("word/document.xml", None)
    end = document.rindex(b"PK\x05\x06")
    stray = b"PK\x05\x06" + b"\x00" * 14
    return {
        "Notes from Tuesday.txt": b"\xff\xfe" + note.encode("utf-16-le"),
        "backup.reg": b"\xff\xfe" + "Windows Registry Editor Version 5.00\r\n".encode("utf-16-le"),
        "be": b"\xfe\xff" + "# Heading\n".encode("utf-16-be"),
        "wide.csv": b"\xff\xfe\x00\x00" + "a,b\n1,2\n3,4\n".encode("utf-32-le"),
        "people.csv": "Name,Ciudad,Año\nJosé,Bogotá,1999\nRenée,Zürich,2001\n".encode("cp1252"),
        "page.htm": "<html><body>Café “crème”</body></html>".encode("cp1252"),
        "old.md": "---\ndate: 2011-03-04\n---\n# Café\n".encode("cp1252"),
        "odd.txt": b"caf\xe9 \x81",
        "Geotag.gpx": b'<?xml version="1.0"?><gpx version="1.1"><trk/></gpx>\n',
        "Info.plist": b'<?xml version="1.0"?><plist/>\n',
        "Makefile": b"all:\n\tcc main.c\n",
        "issue221.xlsm": office_zip("xl/workbook.xml", "application/vnd.ms-excel.sheet.macroEnabled.main+xml"),
        "renamed.xlsx": office_zip("xl/workbook.xml", "application/vnd.ms-excel.template.macroEnabled.main+xml"),
        "deck.pptx": office_zip("ppt/presentation.xml", "application/vnd.openxmlformats-officedocument.presentationml.slideshow.main+xml"),
        "binary.xlsb": office_zip("xl/workbook.bin", None, "application/vnd.ms-excel.sheet.binary.macroEnabled.main"),
        "bare.xltm": office_zip("xl/workbook.xml", None),
        "bare.docm": office_zip("xl/workbook.xml", None),
        "letter.docx": document[: end + 20] + struct.pack("<H", len(stray)) + stray,
        "QuickTime.mov": classic_quicktime(3_500_000_000),
        "clip": classic_quicktime(3_400_000_000),
        "broadcast.ts": transport_stream(5),
        "short.ts": transport_stream(2),
        "IMG_0001.CR3": cr3(canon_tiff, tiff_ifd([(0x9003, 2, b"2021:05:12 10:11:12\x00")])),
        "none.cr3": cr3(canon_tiff, None),
        "latex.pdf": (
            b"%PDF-1.5\n3 0 obj << /Producer (pdfTeX) /CreationDate (D:20170131010939Z) >> endobj\n"
            b"9 0 obj << /Type /XObject /CreationDate (D:20141219120000) >> endobj\ntrailer << /Root 1 0 R /Info 3 0 R >>\n%%EOF\n"
        ),
        "packed.pdf": b"%PDF-1.5\n9 0 obj << /CreationDate (D:20141219120000) >> endobj\ntrailer << /Info 3 0 R >>\n%%EOF\n",
        "bare 2018-02-03.pdf": b"%PDF-1.5\n3 0 obj << /Producer (x) >> endobj\n9 0 obj << /CreationDate (D:20141219) >> endobj\ntrailer << /Info 3 0 R >>\n",
        "deep-512": ("[" * 512 + "]" * 512).encode(),
        "deep-513": ("[" * 513 + "]" * 513).encode(),
        "nan": b"[NaN, Infinity]",
        "bom-json": b'\xef\xbb\xbf{"a": 1}',
        "song.mp3": mp3(2, None),
        "noise.dat": b"\xff\xfb\x90\x64" + bytes(range(256)) * 3,
        "front.md": b"---\ntitle: x\n \t---\t\ndate: 2020-01-02\n",
        "open.md": b"---\ndate: 2020-01-02\n",
        "t.png": png_with_text(" 7\tmar   2014"),
        "a.orf": b"IIRO\x08\x00\x00\x00",
        "zip.bin": plain_zip(1, None),
        "zip.jpeg": plain_zip(2, None),
    }


def blocky_deflate(data: bytes, block: int = 1024) -> bytes:
    """Raw DEFLATE with a new block every `block` bytes."""
    packer = zlib.compressobj(9, zlib.DEFLATED, -15)
    packed = b"".join(packer.compress(data[at : at + block]) + packer.flush(zlib.Z_BLOCK) for at in range(0, len(data), block))
    return packed + packer.flush()


def hand_zip(entries: list[tuple[str, bytes, bytes | None]], comment: bytes = b"") -> bytes:
    """A zip written by hand: (name, data, raw DEFLATE of it or None to store it), then a comment."""
    local, directory = io.BytesIO(), io.BytesIO()
    for name, data, packed in entries:
        method, body = (0, data) if packed is None else (8, packed)
        raw_name, crc, offset = name.encode(), zlib.crc32(data), local.tell()
        local.write(struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0, method, 0, 0x21, crc, len(body), len(data), len(raw_name), 0) + raw_name + body)
        directory.write(struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, 0, method, 0, 0x21, crc, len(body), len(data), len(raw_name), 0, 0, 0, 0, 0, offset) + raw_name)
    table = directory.getvalue()
    end = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, len(entries), len(entries), len(table), local.tell(), len(comment))
    return local.getvalue() + table + end + comment


def core_at(offset: int, date: str = "2016-05-04") -> bytes:
    """docProps/core.xml whose dcterms:created element starts `offset` bytes in."""
    head = b"<cp:coreProperties><!--"
    return head + b"x" * (offset - len(head) - 3) + b"--><dcterms:created>" + date.encode() + b"</dcterms:created></cp:coreProperties>"


def limit_files() -> dict[str, bytes]:
    """Files just inside and just past each reading limit of RULES.md §3 (and the zip end record's)."""
    types = b'<Types><Override PartName="/word/document.xml" ContentType="application/vnd.ms-word.document.macroEnabled.main+xml"/></Types>'
    late_types = b"<Types><!--" + b"y" * 4100 + b'--><Override PartName="/word/document.xml" ContentType="application/vnd.ms-word.document.macroEnabled.main+xml"/></Types>'

    def office(core: bytes, packed_core: bytes | None, content_types: bytes = types) -> bytes:
        return hand_zip([("[Content_Types].xml", content_types, blocky_deflate(content_types)), ("word/document.xml", b"<w:document/>", None), ("docProps/core.xml", core, packed_core)])

    near, far = core_at(3900), core_at(4200)
    exif_app1 = b"\xff\xe1" + struct.pack(">H", 2 + len(exif_bytes("2012-03-04"))) + exif_bytes("2012-03-04")
    comments = lambda count: b"\xff\xfe\x00\x02" * count
    empty_chunk = struct.pack(">I", 0) + b"aaAa" + struct.pack(">I", zlib.crc32(b"aaAa"))
    text_chunk = lambda text: struct.pack(">I", len(text)) + b"tEXt" + text + struct.pack(">I", zlib.crc32(b"tEXt" + text))
    png_head = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0) + b"\x00" * 4
    webp_exif = b"EXIF" + struct.pack("<I", len(exif_bytes("2013-04-05")[6:])) + exif_bytes("2013-04-05")[6:]
    webp = lambda junk: b"RIFF" + struct.pack("<I", 4 + 8 * junk + len(webp_exif)) + b"WEBP" + b"JUNK\x00\x00\x00\x00" * junk + webp_exif
    mvhd = full_box(b"mvhd", 0, 0, struct.pack(">IIII", 3_500_000_000, 3_500_000_000, 600, 600) + b"\x00" * 80)
    mp4 = lambda free: box(b"ftyp", b"isom\x00\x00\x00\x00isom") + box(b"free", b"") * free + box(b"moov", mvhd)
    document = office(near, None)
    end = document.rindex(b"PK\x05\x06")
    strays = b"PK\x05\x06" * 16
    return {
        "within reach.docx": office(near, blocky_deflate(near)),
        "past reach.docx": office(far, blocky_deflate(far)),
        "fifth block.docx": office(core_at(4100 - 1024), blocky_deflate(core_at(4100 - 1024), block=700)),
        "stored past reach.docx": office(far, None),
        "late override.docx": office(near, None, late_types),
        "16 strays.docx": document[: end + 20] + struct.pack("<H", len(strays[:-4])) + strays[:-4],
        "17 strays.docx": document[: end + 20] + struct.pack("<H", len(strays)) + strays,
        "markers within.jpg": b"\xff\xd8" + comments(62) + exif_app1 + b"\xff\xda\x00\x02\xff\xd9",
        "markers past.jpg": b"\xff\xd8" + comments(64) + exif_app1 + b"\xff\xda\x00\x02\xff\xd9",
        "chunks within.png": png_head + empty_chunk * 1022 + text_chunk(b"Creation Time\x002015-06-07"),
        "chunks past.png": png_head + empty_chunk * 1023 + text_chunk(b"Creation Time\x002015-06-07"),
        "text within.png": png_head + text_chunk(b"Creation Time\x00" + b" " * 54 + b"2015-06-07"),
        "text past.png": png_head + text_chunk(b"Creation Time\x00" + b" " * 55 + b"2015-06-07"),
        "chunks within.webp": webp(1023),
        "chunks past.webp": webp(1024),
        "boxes within.mp4": mp4(1022),
        "boxes past.mp4": mp4(1023),
        "csv 1000 lines": b"a,b\n" * 999 + b"a,b,c\n",
        "csv 1001 lines": b"a,b\n" * 1000 + b"a,b,c\n",
    }
