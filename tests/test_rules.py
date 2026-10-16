"""RULES.md in code: the shared modules, name rules, sniffing, embedded dates and the inflater."""

from __future__ import annotations

import base64
import random
import time
import zlib
from pathlib import Path

import builders
import pytest

from plugin import formats, inflate, meta, naming, sniff, walk

ROOT = Path(__file__).resolve().parents[1]
SHARED = ["naming", "inflate", "formats", "sniff", "meta", "walk", "plan", "layout"]


def test_the_verifier_holds_byte_identical_copies_of_the_rules() -> None:
    for name in SHARED:
        assert (ROOT / "src" / "plugin" / f"{name}.py").read_bytes() == (ROOT / "verifier" / f"{name}.py").read_bytes(), name


@pytest.mark.parametrize(
    ("name", "ext"),
    [("photo.JPG", "jpg"), ("a.tar.gz", "gz"), (".bashrc", ""), ("README", ""), ("x.", ""), ("x.toolongextension", ""), ("x.ab-c", ""), ("x.Ｐdf", "")],
)
def test_claimed_extension(name: str, ext: str) -> None:
    assert naming.claimed_ext(name) == ext


@pytest.mark.parametrize("name", [".DS_Store", "thumbs.DB", "Desktop.ini", "Icon\r", "._IMG_1.jpg", "~$report.docx", ".~lock.notes.odt#", "file.TMP", "a.part", "x.crdownload"])
def test_junk_names(name: str) -> None:
    assert naming.is_junk(name) and not naming.is_hidden(name)


def test_hidden_names_are_the_dot_names_that_are_not_junk() -> None:
    assert naming.is_hidden(".git") and naming.is_hidden(".env") and not naming.is_hidden("a.git")


@pytest.mark.parametrize(
    ("stem", "date"),
    [
        ("IMG_20180305_120102", "2018-03-05"),
        ("Photo 2019-07-14 10.22.31", "2019-07-14"),
        ("scan 2019.07.14", "2019-07-14"),
        ("2019-07_14", None),  # the two separators differ
        ("receipt 20210229", None),  # not a leap year
        ("old 19850601", None),  # before 1990
        ("future 20400101", None),  # after 2039
        ("id 1201907145", None),  # touching other digits
        ("٢٠١٩-٠٧-١٤", None),  # Unicode digits are not digits here
        ("first 2019-13-45 then 2020-01-02", "2020-01-02"),
    ],
)
def test_dates_in_names(stem: str, date: str | None) -> None:
    found = naming.name_date(stem)
    assert (found[0] if found else None) == date


@pytest.mark.parametrize(
    ("stem", "slug"),
    [
        ("Copy of Report (1)", "report"),
        ("report - Copy (2)", "report"),
        ("report copy 2", "report"),
        ("report_copy3", "report"),
        ("report (1) - Copy", "report"),
        ("photo 2", "photo-2"),
        ("Résumé – Jürgen Müller", "resume-jurgen-muller"),
        ("日本語メモ", "file"),
        ("IMG_20180305_120102", "img-120102"),
        ("ＡＢＣ report", "abc-report"),
        ("final v2", "final-v2"),
        ("a" * 70, "a" * 60),
        ("x" * 59 + "-yy", "x" * 59),
    ],
)
def test_slugs(stem: str, slug: str) -> None:
    assert naming.slug_of(stem) == slug


def test_scheme_form_names_keep_their_slug_and_date() -> None:
    assert naming.name_facts("2019-07-14_beach_3.jpg", "jpg") == ("2019-07-14", "beach")
    assert naming.name_facts("undated_notes.tar.gz", "tar.gz") == (None, "notes")
    assert naming.name_facts("1975-01-02_old.pdf", "pdf") == ("1975-01-02", "old")  # embedded-range years are accepted
    assert naming.name_facts("2019-07-14_Beach.jpg", "jpg") == ("2019-07-14", "beach")  # not scheme form: a slug


def test_base_paths_and_conforming() -> None:
    base = naming.base_path("images", "jpg", "jpg", "2019-07-14", "beach")
    assert base == "organized/images/jpg/2019/2019-07-14_beach.jpg"
    assert naming.base_path("archives", "gz", "tar.gz", None, "logs") == "organized/archives/gz/undated/undated_logs.tar.gz"
    assert naming.conforms(base, base, "jpg") and naming.conforms(base.replace(".jpg", "_2.jpg"), base, "jpg")
    assert naming.conforms(base.replace(".jpg", "_12.jpg"), base, "jpg")
    for other in (base.replace(".jpg", "_1.jpg"), base.replace(".jpg", "_02.jpg"), base.replace(".jpg", "_x.jpg"), base + ".jpg"):
        assert not naming.conforms(other, base, "jpg")


def kind(data: bytes, name: str = "x") -> tuple[str, str, str]:
    found = sniff.sniff(data, name, naming.claimed_ext(name))
    return found.group, found.type, found.ext


@pytest.mark.parametrize(
    ("sample", "name", "expected"),
    [
        ("jpg", "x.png", ("images", "jpg", "jpg")),
        ("jpg", "x.jpeg", ("images", "jpg", "jpg")),
        ("png", "x", ("images", "png", "png")),
        ("tiff", "x.tif", ("images", "tiff", "tiff")),
        ("tiff", "x.NEF", ("images", "raw", "nef")),
        ("heic", "x.jpg", ("images", "heic", "heic")),
        ("avif", "x", ("images", "avif", "avif")),
        ("mov", "x.mp4", ("video", "mov", "mov")),
        ("m4a", "x", ("audio", "m4a", "m4a")),
        ("docx", "x.zip", ("documents", "docx", "docx")),
        ("xlsx", "x", ("spreadsheets", "xlsx", "xlsx")),
        ("pptx", "x", ("presentations", "pptx", "pptx")),
        ("odt", "x", ("documents", "odt", "odt")),
        ("ods", "x", ("spreadsheets", "ods", "ods")),
        ("odp", "x", ("presentations", "odp", "odp")),
        ("epub", "x.zip", ("documents", "epub", "epub")),
        ("zip", "x.docx", ("archives", "zip", "zip")),
        ("zip", "x.pages", ("other", "pages", "pages")),
        ("jar", "x.jar", ("other", "jar", "jar")),
        ("gz", "logs.TGZ", ("archives", "gz", "tar.gz")),
        ("gz", "x.gz", ("archives", "gz", "gz")),
        ("bin", "x.dat", ("other", "dat", "dat")),
        ("bin", "x.jpeg", ("other", "bin", "bin")),
        ("bin", "x.txt", ("other", "bin", "bin")),
        ("bin", "x", ("other", "bin", "bin")),
        ("txt", "x.jpg", ("documents", "txt", "txt")),
        ("csv", "x.txt", ("documents", "txt", "txt")),
        ("csv", "x", ("spreadsheets", "csv", "csv")),
        ("json", "x", ("data", "json", "json")),
        ("log", "x", ("data", "log", "log")),
        ("html", "x", ("documents", "html", "html")),
        ("svg", "x.png", ("images", "svg", "svg")),
        ("yaml", "x.yml", ("data", "yaml", "yaml")),
        ("md", "notes.markdown", ("documents", "md", "md")),
        ("rtf", "x", ("documents", "rtf", "rtf")),
    ],
)
def test_sniffing_by_content(sample: str, name: str, expected: tuple[str, str, str]) -> None:
    assert kind(builders.SAMPLES[sample](4, "2019-07-14"), name) == expected


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"ID3\x03\x00rest", ("audio", "mp3", "mp3")),
        (b"ID3 tags are notes", ("documents", "txt", "txt")),  # text, not an ID3 header
        (b"\xff\xfb\x90\x64" + b"\x00" * 20, ("audio", "mp3", "mp3")),
        (b"\xff\xf1\x50\x80" + b"\x00" * 20, ("other", "bin", "bin")),  # AAC ADTS: layer bits 00
        (b"RIFF\x10\x00\x00\x00WEBPVP8 ", ("images", "webp", "webp")),
        (b"\x00\x00\x00\x18ftypmif1\x00\x00\x00\x00mif1avif", ("images", "avif", "avif")),
        (b"\x00\x00\x00\x14ftypmif1\x00\x00\x00\x00mif1", ("images", "heic", "heic")),
        (b"\x00\x00\x00\x14ftypcrx \x00\x00\x00\x01crx ", ("images", "raw", "cr3")),
        (b"\x00\x00\x00\x14ftypisom\x00\x00\x02\x00isom", ("video", "mp4", "mp4")),
        (b"FUJIFILMCCD-RAW 0201", ("images", "raw", "raf")),
        (b"\x1a\x45\xdf\xa3\x93\x42\x82\x88matroska", ("video", "mkv", "mkv")),
        (b"PK\x05\x06" + b"\x00" * 18, ("archives", "zip", "zip")),
        (b"\xef\xbb\xbf# Title\n", ("documents", "md", "md")),
        (b'<?xml version="1.0"?>\n<svg/>', ("images", "svg", "svg")),
        (b'<?xml version="1.0"?><?other x?><svg/>', ("documents", "txt", "txt")),  # svg must follow the first ?>
        (b"<!DOCTYPE HTML><p>", ("documents", "html", "html")),
        (b"a,b\n\n1,2\n3,4\n", ("spreadsheets", "csv", "csv")),
        (b"a,b\n1,2\n3\n", ("documents", "txt", "txt")),
        (b"2021-05-06T10:00:00 start\n", ("data", "log", "log")),
        (b"text\x00with nul", ("other", "bin", "bin")),
    ],
)
def test_sniffing_edge_rows(data: bytes, expected: tuple[str, str, str]) -> None:
    assert kind(data) == expected


@pytest.mark.parametrize("sample", sorted(builders.DATED))
def test_every_dated_type_gives_its_embedded_date(sample: str) -> None:
    facts = walk.describe("x." + builders.natural_ext(sample), builders.SAMPLES[sample](8, "2016-02-29"))
    assert facts.date == "2016-02-29" and facts.date_source not in ("name", "none")
    undated = walk.describe("x." + builders.natural_ext(sample), builders.SAMPLES[sample](8, None))
    assert undated.date is None and undated.date_source == "none"


def test_embedded_dates_win_over_names_and_only_real_dates_in_range_count() -> None:
    assert walk.describe("IMG_20180305.jpg", builders.jpeg(1, "2019-07-14")).date == "2019-07-14"
    assert walk.describe("IMG_20180305.jpg", builders.jpeg(1, None)).date == "2018-03-05"
    for stored, expected in (("1970-12-31", None), ("1971-01-01", "1971-01-01"), ("2099-12-31", "2099-12-31"), ("2100-01-01", None)):
        exif = builders.exif_bytes(None)
        data = builders.saved(builders.picture(1), "JPEG", exif=exif)
        found = meta.dated(meta.EXIF, stored, meta.EXIF_DATE.match(stored.replace("-", ":")))
        assert (found[2] if found else None) == expected, stored
        assert data


def test_pdf_the_last_creation_date_counts() -> None:
    assert walk.describe("x.pdf", builders.pdf(1, "2015-03-04", updated="2020-05-06")).date == "2020-05-06"
    hex_only = b"%PDF-1.4\n3 0 obj << /CreationDate <FEFF00440020> >> endobj\n%%EOF\n"
    assert walk.describe("x.pdf", hex_only).date is None


def test_png_exif_comes_before_text_and_rfc_dates_read() -> None:
    assert walk.describe("x.png", builders.png_text(1, "2011-12-13", rfc=True)).date == "2011-12-13"
    assert walk.describe("x.png", builders.png_text(1, "2011-12-13")).date_source == "png-text"


@pytest.mark.parametrize(
    ("text", "date"),
    [
        ("---\ndate: '2019-07-14'\n---\n# x", "2019-07-14"),
        ("---\ntitle: x\n  ---  \ndate: 2019-07-14\n", None),  # after the closing line
        ("# x\n---\ndate: 2019-07-14\n---\n", None),  # no front matter
        ("---\r\ndate: \"2019-07-14T10:00\"\r\n---\r\n", "2019-07-14"),
    ],
)
def test_front_matter_dates(text: str, date: str | None) -> None:
    assert walk.describe("note.md", text.encode()).date == date


def test_media_creation_time_zero_means_none() -> None:
    assert walk.describe("x.mp4", builders.mp4(1, None)).date is None
    assert walk.describe("x.mov", builders.mov(1, "1999-12-31")).date == "1999-12-31"


def test_zip_entries_read_stored_and_deflated_and_refuse_others() -> None:
    for data in (builders.ooxml("docx", 1, "2001-02-03", deflate=True), builders.ooxml("docx", 1, "2001-02-03", deflate=False)):
        assert formats.zip_member(data, "docProps/core.xml") is not None
    assert formats.zip_member(b"PK\x03\x04 not really", "x") is None


@pytest.mark.parametrize("level", range(10))
def test_the_inflater_matches_zlib(level: int) -> None:
    rng = random.Random(level)
    for size in (0, 1, 7, 300, 5000, 70000):
        for data in (bytes(rng.randrange(256) for _ in range(size)), (b"<w:t>lorem ipsum</w:t>" * (size // 20 + 1))[:size]):
            for strategy in (zlib.Z_DEFAULT_STRATEGY, zlib.Z_FIXED, zlib.Z_HUFFMAN_ONLY, zlib.Z_RLE):
                packer = zlib.compressobj(level, zlib.DEFLATED, -15, 8, strategy)
                packed = packer.compress(data) + packer.flush()
                assert inflate.inflate(packed, 1 << 20, 1 << 20) == data
                assert inflate.inflate(packed, 4096, 1 << 20) == data[:4096]  # the start, as far as the limit


def packed_bits(bits: list[int]) -> bytes:
    """Bits packed as DEFLATE reads them: each byte's lowest bit first."""
    return bytes(sum(bit << shift for shift, bit in enumerate(bits[at : at + 8])) for at in range(0, len(bits), 8))


def test_the_inflater_refuses_bad_streams_and_bounds_its_work() -> None:
    assert inflate.inflate(b"\xff\xff\xff", 100, 4) is None
    packer = zlib.compressobj(9, zlib.DEFLATED, -15)
    bomb = packer.compress(b"\x00" * 2_000_000) + packer.flush()
    assert inflate.inflate(bomb, 4096, 4) == b"\x00" * 4096  # a bomb: only its first 4,096 bytes
    empty_blocks = packed_bits(([0, 1, 0] + [0] * 7) * 100_000 + [1, 1, 0] + [0] * 7)  # fixed blocks that end at once
    started = time.perf_counter()
    assert inflate.inflate(empty_blocks, 4096, 4) == b""  # only the first 4 blocks are read
    assert time.perf_counter() - started < 0.01
    literal_heavy = zlib.compressobj(9, zlib.DEFLATED, -15)
    text = base64.b64encode(random.Random(1).randbytes(600_000))
    packed = literal_heavy.compress(text) + literal_heavy.flush()
    started = time.perf_counter()
    assert inflate.inflate(packed, 4096, 4) == text[:4096]
    assert time.perf_counter() - started < 0.05
