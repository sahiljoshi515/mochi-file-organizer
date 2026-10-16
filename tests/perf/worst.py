"""Folders at the published limits, built to cost the rules the most (tests/test_perf.py,
tests/perf/verifier_times.py): every file a reader walks to its cap, every zip part dense to its
4,096-byte reach, the challenger's dense .docx folders (perf_dense45/90), and the byte and file limits.

A folder is {path in the agent folder: bytes}, deterministic for its name.
"""

from __future__ import annotations

import base64
import io
import json
import random
import struct
import zipfile
import zlib

MiB = 1 << 20
CT_MAIN = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"


def dense(rng: random.Random, size: int) -> bytes:
    """Base64 of random bytes: DEFLATE can only code it as literals, the most costly output."""
    return base64.b64encode(rng.randbytes(size * 3 // 4 + 3))[:size]


def deflated_zip(entries: list[tuple[str, bytes]], padding: int = 0) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for index in range(padding):
            archive.writestr(f"customXml/item{index}.xml", b"")
        for name, data in entries:
            archive.writestr(name, data)
    return buffer.getvalue()


def blocky(data: bytes, block: int = 1024) -> bytes:
    """Raw DEFLATE with a new dynamic block every `block` bytes: the most costly stream to start reading."""
    packer = zlib.compressobj(9, zlib.DEFLATED, -15)
    packed = b"".join(packer.compress(data[at : at + block]) + packer.flush(zlib.Z_BLOCK) for at in range(0, len(data), block))
    return packed + packer.flush()


def raw_zip(entries: list[tuple[str, bytes]], padding: int = 0) -> bytes:
    """A zip written by hand, each entry deflated by `blocky`, behind `padding` empty stored entries."""
    local, directory = io.BytesIO(), io.BytesIO()
    items = [(f"customXml/item{index}.xml", b"", 0) for index in range(padding)] + [(name, data, 8) for name, data in entries]
    for name, data, method in items:
        packed = blocky(data) if method == 8 else data
        raw_name, crc, offset = name.encode(), zlib.crc32(data), local.tell()
        local.write(struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0, method, 0, 0x21, crc, len(packed), len(data), len(raw_name), 0) + raw_name + packed)
        directory.write(struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, 0, method, 0, 0x21, crc, len(packed), len(data), len(raw_name), 0, 0, 0, 0, 0, offset) + raw_name)
    cd = directory.getvalue()
    end = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, len(items), len(items), len(cd), local.tell(), 0)
    return local.getvalue() + cd + end


def dense_docx(rng: random.Random, part: int, padding: int = 0) -> bytes:
    """A .docx whose [Content_Types].xml and docProps/core.xml are `part` bytes of dense text, with the
    elements the rules want after them (out of reach), behind `padding` other central-directory entries."""
    types = b'<?xml version="1.0"?><Types><!--' + dense(rng, part) + b'--><Override PartName="/word/document.xml" ContentType="' + CT_MAIN.encode() + b'"/></Types>'
    core = b"<cp:coreProperties><!--" + dense(rng, part) + b"--><dcterms:created>2011-11-12</dcterms:created></cp:coreProperties>"
    return raw_zip([("[Content_Types].xml", types), ("word/document.xml", b"<w:document/>"), ("docProps/core.xml", core)], padding)


def dense_office(count: int = 1000, part: int = 8 * 1024, padding: int = 1500) -> dict[str, bytes]:
    """`count` dense .docx files (by default 1,000 files, about 175 MiB): every part read to its 4,096-byte
    reach through 4 dynamic blocks, behind 1,500 other central-directory entries."""
    rng = random.Random(f"dense-office:{count}:{part}")
    return {f"Downloads/report {index:04d}.docx": dense_docx(rng, part, padding) for index in range(count)}


def challenger_dense(count: int) -> dict[str, bytes]:
    """The review's perf_dense45 / perf_dense (90): .docx files whose core.xml is ~1 MiB of dense text."""
    rng = random.Random(f"challenger-dense:{count}")
    files = {}
    for index in range(count):
        core = b"<cp:coreProperties><!--" + dense(rng, MiB - 300) + b"--><dcterms:created>2011-11-12</dcterms:created></cp:coreProperties>"
        types = b'<?xml version="1.0"?><Types><Override PartName="/word/document.xml" ContentType="' + CT_MAIN.encode() + b'"/></Types>'
        files[f"Downloads/dense-meta {index:03d}.docx"] = deflated_zip([("[Content_Types].xml", types), ("word/document.xml", b"<w:document/>"), ("docProps/core.xml", core)])
    return files


def jpeg_markers(rng: random.Random, size: int) -> bytes:
    return b"\xff\xd8" + b"\xff\xfe\x00\x02" * 80 + rng.randbytes(max(0, size - 324)) + b"\xff\xd9"


def png_chunks(rng: random.Random, size: int) -> bytes:
    chunk = struct.pack(">I", 0) + b"aaAa" + struct.pack(">I", zlib.crc32(b"aaAa"))
    body = b"\x89PNG\r\n\x1a\n" + chunk * 1100
    return body + rng.randbytes(max(0, size - len(body)))


def webp_chunks(rng: random.Random, size: int) -> bytes:
    body = b"WEBP" + b"JUNK\x00\x00\x00\x00" * 1100
    body += rng.randbytes(max(0, size - len(body) - 8))
    return b"RIFF" + struct.pack("<I", len(body)) + body


def mp4_boxes(rng: random.Random, size: int) -> bytes:
    head = b"\x00\x00\x00\x10ftypisom\x00\x00\x00\x00" + b"\x00\x00\x00\x08free" * 1100
    tail = rng.randbytes(max(0, size - len(head) - 8))
    return head + struct.pack(">I", len(tail) + 8) + b"mdat" + tail


def tiff_ifds(rng: random.Random, size: int) -> bytes:
    """A TIFF whose IFD0 and Exif IFD hold 1,024 entries each, the wanted tag in neither."""
    exif_at = 8 + 2 + 12 * 1024 + 4
    ifd0 = struct.pack("<H", 1024) + b"".join(struct.pack("<HHII", 0x0100 + index, 3, 1, 0) for index in range(1023)) + struct.pack("<HHII", 0x8769, 4, 1, exif_at) + b"\x00" * 4
    exif = struct.pack("<H", 1024) + b"".join(struct.pack("<HHII", 0x9000 + index % 3, 3, 1, 0) for index in range(1024)) + b"\x00" * 4
    body = b"II*\x00" + struct.pack("<I", 8) + ifd0 + exif
    return body + rng.randbytes(max(0, size - len(body)))


def heif_items(rng: random.Random, size: int) -> bytes:
    """A HEIF whose iloc lists 1,024 items of one extent before the Exif item's."""
    box = lambda kind, body: struct.pack(">I", 8 + len(body)) + kind + body
    full = lambda kind, version, body: box(kind, bytes([version, 0, 0, 0]) + body)
    infe = full(b"infe", 2, struct.pack(">HH", 5000, 0) + b"Exif\x00")
    iinf = full(b"iinf", 0, struct.pack(">H", 1) + infe)
    items = b"".join(struct.pack(">HHHII", index, 0, 1, 0, 1) for index in range(1024)) + struct.pack(">HHHII", 5000, 0, 1, 0, 8)
    iloc = full(b"iloc", 0, bytes([0x44, 0x00]) + struct.pack(">H", 1025) + items)
    head = box(b"ftyp", b"heic\x00\x00\x00\x00mif1heic") + full(b"meta", 0, iinf + iloc)
    return head + rng.randbytes(max(0, size - len(head)))


def pdf_literals(rng: random.Random, size: int) -> bytes:
    unit = b"/CreationDate (D:2014121900) "
    return b"%PDF-1.5\n" + unit * (size // len(unit)) + b"\n/Info 3 0 R\n%%EOF\n"


def json_text(rng: random.Random, size: int) -> bytes:
    """Valid JSON nested 512 deep around a long string of escapes: the whole JSON check runs."""
    return b"[" * 511 + b'["' + b'a\\"' * ((size - 1100) // 3) + b'"]' + b"]" * 511


def csv_lines(rng: random.Random, size: int) -> bytes:
    return b"a,b\n" * (size // 4)


def legacy_text(rng: random.Random, size: int) -> bytes:
    return ("caf\xe9 " * (size // 5)).encode("cp1252")


def wide_text(rng: random.Random, size: int) -> bytes:
    return b"\xff\xfe" + ("x," * (size // 4) + "\n").encode("utf-16-le")


def big_directory_zip(rng: random.Random, size: int) -> bytes:
    """A zip whose central directory is most of the file; its Office part last."""
    count = max(1, size // 80)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        for index in range(count):
            archive.writestr(f"e{index}", b"")
        archive.writestr("word/document.xml", b"<w:document/>")
    return buffer.getvalue()


KINDS = [
    ("jpg", jpeg_markers), ("png", png_chunks), ("webp", webp_chunks), ("mp4", mp4_boxes), ("tif", tiff_ifds),
    ("heic", heif_items), ("pdf", pdf_literals), ("json", json_text), ("csv", csv_lines), ("txt", legacy_text),
    ("log", wide_text), ("zip", big_directory_zip),
]  # fmt: skip


def mixed_worst(count: int = 1000, total: int = 190 * MiB) -> dict[str, bytes]:
    """`count` files of every costly kind above, `total` bytes in all, named without an extension or with
    a misleading one so every content check runs."""
    rng = random.Random(f"mixed-worst:{count}:{total}")
    size = total // count - 64  # each builder stays within about 8% of it: the folder holds under 200 MiB
    files = {}
    for index in range(count):
        ext, build = KINDS[index % len(KINDS)]
        name = f"Downloads/{ext}-{index:04d}" + ("" if index % 2 else ".bin")
        files[name] = build(rng, size)
    return files


def json_folder(count: int = 19, size: int = 10 * MiB) -> dict[str, bytes]:
    """The costliest text per byte: valid JSON of many short strings, no extension, up to 200 MiB."""
    return {f"Downloads/export-{index:02d}": b"[" + b'"ab",' * ((size - 8) // 5) + f'"{index}"]'.encode() for index in range(count)}


def combined_worst() -> dict[str, bytes]:
    """The costliest per file and the costliest per byte at once: 982 small dense .docx files and 18
    files of 10 MiB of JSON text, 1,000 files and about 190 MiB."""
    files = dense_office(982, 8 * 1024, 0)
    files.update(json_folder(18))
    return files


def with_outside(files: dict[str, bytes], outside: int, piece: int = 8 * MiB) -> dict[str, bytes]:
    """`files` plus `outside` bytes of other files elsewhere in the agent folder (the verifier hashes them)."""
    rng = random.Random(f"outside:{outside}")
    more = dict(files)
    for index in range(outside // piece):
        more[f"Archive/part {index:03d}.bin"] = rng.randbytes(piece)
    return more


def organized(files: dict[str, bytes]) -> dict[str, bytes]:
    """The same files already at their places: an idle run, where verify_task re-reads every one."""
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(root / "src"), str(root)]
    from plugin.walk import describe

    placed = {}
    for path, data in files.items():
        folder, _sep, name = path.partition("/")
        placed[f"{folder}/{describe(name, data).base}"] = data
    return placed


FOLDERS = {
    "dense-office-1000": lambda: dense_office(),
    "organized-dense-1000": lambda: organized(dense_office()),
    "challenger-dense45": lambda: challenger_dense(45),
    "challenger-dense90": lambda: challenger_dense(90),
    "mixed-worst-1000": lambda: mixed_worst(),
    "json-190mib": lambda: json_folder(),
    "limits-1gib": lambda: with_outside(mixed_worst(), 1024 * MiB - 208 * MiB),
    "combined-worst-1gib": lambda: with_outside(combined_worst(), 1024 * MiB - 200 * MiB),
}


def describe_folder(name: str) -> str:
    files = FOLDERS[name]()
    taking = [path for path in files if path.startswith("Downloads/")]
    return json.dumps({"folder": name, "files": len(taking), "bytes": sum(len(files[path]) for path in taking), "agent_bytes": sum(map(len, files.values()))})
