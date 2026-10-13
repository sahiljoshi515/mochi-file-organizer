from __future__ import annotations

import ast
import datetime
import io
import random
from pathlib import Path

import pytest
from PIL import Image

from plugin import generate, rules

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_IMPORTS = {
    "__future__", "collections", "dataclasses", "decimal", "difflib", "enum", "fractions", "functools", "hashlib",
    "itertools", "json", "math", "operator", "pathlib", "re", "statistics", "string", "textwrap", "typing", "unicodedata",
}  # fmt: skip
FORBIDDEN_NAMES = {"__import__", "breakpoint", "compile", "delattr", "eval", "exec", "getattr", "globals", "input", "locals", "open", "setattr", "vars"}
FORBIDDEN_ATTRIBUTES = {"builtins", "chmod", "hardlink_to", "mkdir", "os", "rename", "rmdir", "shutil", "socket", "subprocess", "symlink_to", "sys", "touch", "unlink", "write_bytes", "write_text"}


def row(**changes) -> rules.Row:
    base = {"path": "inbox/a.txt", "size": 1, "sha256": "a" * 64, "type": "txt", "ext": "txt", "exif": None, "png": None, "pdf": None, "md": None, "mtime_utc": "2020-01-02T03:04:05Z"}
    return rules.Row(**{**base, **changes})


def test_the_server_side_rules_are_a_byte_identical_copy() -> None:
    assert (ROOT / "verifier" / "rules.py").read_bytes() == (ROOT / "src" / "plugin" / "rules.py").read_bytes()


def test_the_readme_quotes_the_rules_verbatim() -> None:
    assert (ROOT / "src" / "plugin" / "RULES.md").read_text(encoding="utf-8") in (ROOT / "README.md").read_text(encoding="utf-8")


def test_the_verifier_uses_only_what_a_verifier_may() -> None:
    for module in sorted((ROOT / "verifier").glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] in ALLOWED_IMPORTS for alias in node.names), (module.name, ast.dump(node))
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                assert (node.module or "").split(".")[0] in ALLOWED_IMPORTS | {"contract"}, (module.name, node.module)
            elif isinstance(node, ast.Name):
                assert node.id not in FORBIDDEN_NAMES, (module.name, node.id)
            elif isinstance(node, ast.Attribute):
                assert node.attr not in FORBIDDEN_ATTRIBUTES and not node.attr.startswith("_"), (module.name, node.attr)


def test_utc_stamp_agrees_with_datetime() -> None:
    rng = random.Random(7)
    samples = [0, 86399, 86400, 951782400, 951868800, 4107456000, 1709164800] + [rng.randint(0, 4_000_000_000) for _ in range(5000)]
    for seconds in samples:
        want = datetime.datetime.fromtimestamp(seconds, datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        assert rules.utc_stamp(seconds) == want


@pytest.mark.parametrize("kind", generate.KINDS)
def test_every_generated_kind_sniffs_as_itself(kind: str) -> None:
    meta = {"exif": "2019:07:14 10:22:31", "png": "2019-07-14T10:22:31Z", "pdf": "D:20190714102231Z", "md": "2019-07-14"}
    for draw in range(6):
        assert rules.sniff(generate.content(kind, "id00001", meta, draw)) == kind
        assert rules.sniff(generate.content(kind, "id00002", {}, draw)) == kind


@pytest.mark.parametrize(
    ("data", "kind"),
    [
        (b"", "txt"),
        (b"\xff\xfe\x00bytes", "bin"),
        (b"text with a \x00 byte", "bin"),
        (b'<?xml version="1.0"?>\n<svg xmlns="x"></svg>', "svg"),
        (b"  <SVG>", "svg"),
        (b"<!doctype HTML>", "html"),
        (b"<html lang='en'>", "html"),
        (b"<htmlx>", "txt"),
        (b"#!/usr/bin/python\nprint(1)\n", "py"),
        (b"#!/bin/sh\necho\n", "txt"),
        (b'{"a": 1}', "json"),
        (b"[1, 2]", "json"),
        (b"42", "txt"),
        (b"{not json", "txt"),
        (b"2021-03-04 05:06:07 INFO x", "log"),
        (b"2021-03-04T05:06:07Z INFO x", "log"),
        (b"# Title\n", "md"),
        (b"#Title\n", "txt"),
        (b"---\ndate: 2019-07-14\n---\n", "md"),
        (b"a,b\nc,d\ne,f\n", "csv"),
        (b"a,b\nc,d\n", "txt"),
        (b"a,b\nc,d,e\nf,g\n", "txt"),
        (b"a\nb\nc\n", "txt"),
        (b"%PDF-1.4 junk", "pdf"),
        (b"\x89PNG\r\n\x1a\nrest", "png"),
        (b"\xff\xd8\xffrest", "jpg"),
    ],
)
def test_sniffing_edge_cases(data: bytes, kind: str) -> None:
    assert rules.sniff(data) == kind


def test_a_zip_without_a_word_document_is_a_zip() -> None:
    assert rules.sniff(generate.zip_bytes([("a.txt", b"x")])) == "zip"
    assert rules.sniff(generate.docx_bytes("hello")) == "docx"
    assert "word/document.xml" in rules.zip_names(generate.docx_bytes("hello"))
    assert rules.zip_names(b"PK\x03\x04 truncated") == []


def test_exif_reader_agrees_with_pillow() -> None:
    for fixture in generate.FIXTURES:
        data = generate.jpeg_bytes(fixture, "2019:07:14 10:22:31", "id00001")
        assert rules.exif_datetime(data) == "2019:07:14 10:22:31"
        assert Image.open(io.BytesIO(data)).getexif().get_ifd(0x8769)[0x9003] == "2019:07:14 10:22:31"
        assert rules.exif_datetime(generate.jpeg_bytes(fixture, None, "id00001")) is None


def test_png_pdf_and_front_matter_readers() -> None:
    png = generate.png_bytes(3, 2, (1, 2, 3), "Sun, 14 Jul 2019 10:22:31 GMT", "id00001")
    assert rules.png_creation_time(png) == "Sun, 14 Jul 2019 10:22:31 GMT"
    assert rules.png_creation_time(generate.png_bytes(3, 2, (1, 2, 3), None, "id00001")) is None
    assert Image.open(io.BytesIO(png)).size == (3, 2)
    assert rules.pdf_creation_date(generate.pdf_bytes("T", "x", "D:20190714102231+02'00'")) == "D:20190714102231+02'00'"
    assert rules.pdf_creation_date(generate.pdf_bytes("T", "x", None)) is None
    assert rules.frontmatter_date("---\ntitle: a\ndate: \"2019-07-14\"\n---\n# a\n") == '"2019-07-14"'
    assert rules.frontmatter_date("---\ntitle: a\n---\ndate: 2019-07-14\n") is None
    assert rules.frontmatter_date("# a\ndate: 2019-07-14\n") is None


@pytest.mark.parametrize(
    ("changes", "date"),
    [
        ({"exif": "2019:07:14 10:22:31"}, "2019-07-14"),
        ({"png": "Sun, 14 Jul 2019 10:22:31 GMT"}, "2019-07-14"),
        ({"png": "2019-07-14T10:22:31Z"}, "2019-07-14"),
        ({"pdf": "D:20190714102231+02'00'"}, "2019-07-14"),
        ({"pdf": "D:20190714"}, "2019-07-14"),
        ({"md": "'2019-07-14'"}, "2019-07-14"),
        ({"md": "2019-07-14T10:22:31Z"}, "2019-07-14"),
        ({"md": "14 July 2019"}, None),
        ({"exif": "2019:13:14 10:22:31"}, None),
        ({"png": "31 Apr 2019 10:22:31 GMT"}, None),
        ({"exif": "2019:13:14 10:22:31", "png": "2018-01-01T00:00:00Z"}, "2018-01-01"),
    ],
)
def test_embedded_dates(changes: dict, date: str | None) -> None:
    assert rules.embedded_date(row(**changes)) == date


def test_date_precedence_embedded_then_name_then_mtime() -> None:
    assert rules.file_date(row(path="inbox/x/IMG_2018-01-01.jpg", exif="2019:07:14 10:22:31")) == "2019-07-14"
    assert rules.file_date(row(path="inbox/x/IMG_2018-01-01.jpg", exif="2019:13:14 10:22:31")) == "2018-01-01"
    assert rules.file_date(row(path="inbox/2018-01-01/scan_2019-13-45.pdf")) == "2020-01-02"
    assert rules.file_date(row(path="inbox/x/a.txt", mtime_utc="2021-12-31T23:59:59Z")) == "2021-12-31"


@pytest.mark.parametrize(
    ("name", "date"),
    [
        ("IMG_20190714.jpg", "2019-07-14"),
        ("scan_2019-13-45.pdf", None),
        ("IMG_201907141022.jpg", None),
        ("backup-1985-06-01.zip", None),
        ("2019-02-30 then 2019-03-01.txt", "2019-03-01"),
        ("v20190714-2.txt", "2019-07-14"),
        ("2031-05-06.txt", None),
        ("20200229.csv", "2020-02-29"),
        ("20210229.csv", None),
        ("2019-0714.txt", None),
    ],
)
def test_name_dates(name: str, date: str | None) -> None:
    assert rules.name_date(name) == date


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("report (1)", "report"),
        ("report - copy (2).pdf", "report"),
        ("Résumé – Jürgen final.docx", "resume-jurgen"),
        ("Résumé – Jürgen (final).docx", "resume-jurgen-final"),
        ("IMG_0042 (1).JPG", "img-0042"),
        ("notes_v2.txt", "notes"),
        ("project (1) final.pdf", "project"),
        ("日本語メモ.txt", "file"),
        ("_v3.txt", "file"),
        ("ﬁnal report.md", "final-report"),
        (".DS_Store", "ds-store"),
        ("Mr. Smith letter", "mr-smith-letter"),
        ("a.b.c", "a-b"),
        ("ＡＢＣ.txt", "abc"),
        ("Copy of x.txt", "copy-of-x"),
        ("x copy3.txt", "x"),
        ("x-FINAL.txt", "x"),
        ("Photo 2019-07-14 10.22.31.jpg", "photo-2019-07-14-10-22-31"),
    ],
)
def test_slugs(name: str, expected: str) -> None:
    assert rules.slug(name) == expected


def test_claimed_extensions_and_junk() -> None:
    assert rules.claimed_ext("Thumbs.db") == "db"
    assert rules.claimed_ext("archive.tar.gz") == "gz"
    assert rules.claimed_ext(".DS_Store") == ""
    assert rules.claimed_ext("Mr. Smith letter") == ""
    assert rules.claimed_ext("a.") == ""
    assert rules.claimed_ext("IMG_0042.JPEG") == "JPEG"
    assert rules.stem("IMG_0042.JPEG") == "IMG_0042"
    assert all(rules.is_junk(name) for name in [".DS_Store", ".ds_store", "Thumbs.db", "thumbs.DB", "desktop.ini", "~$x.docx", "a.tmp", "a.TMP", "x.part"])
    assert not any(rules.is_junk(name) for name in ["part.txt", "tmp", "DS_Store", "x.tmpx", "desktop.ini.txt"])


def test_plan_keeps_the_earliest_copy_then_the_smallest_path() -> None:
    rows = [
        row(path="inbox/b/x.txt", sha256="1" * 64, mtime_utc="2020-01-02T00:00:00Z"),
        row(path="inbox/a/Copy of x.txt", sha256="1" * 64, mtime_utc="2020-01-01T00:00:00Z"),
        row(path="inbox/c/x (1).txt", sha256="1" * 64, mtime_utc="2020-01-03T00:00:00Z"),
        row(path="inbox/z/y.txt", sha256="2" * 64, mtime_utc="2020-05-05T00:00:00Z"),
        row(path="inbox/a/y.txt", sha256="2" * 64, mtime_utc="2020-05-05T00:00:00Z"),
    ]
    planned = rules.plan(rows)
    assert dict(planned.moves) == {"inbox/a/Copy of x.txt": "organized/documents/txt/2020/2020-01-01_copy-of-x.txt", "inbox/a/y.txt": "organized/documents/txt/2020/2020-05-05_y.txt"}
    assert planned.deletes == ("inbox/b/x.txt", "inbox/c/x (1).txt", "inbox/z/y.txt")
    assert (planned.unique, planned.duplicates, planned.removed) == (2, 3, 0)


def test_plan_deletes_junk_and_empty_files_and_keeps_near_duplicates() -> None:
    rows = [
        row(path="inbox/a/.DS_Store", sha256="1" * 64, type="bin"),
        row(path="inbox/a/report.TMP", sha256="2" * 64),
        row(path="inbox/a/empty.png", sha256="3" * 64, size=0, type="png"),
        row(path="inbox/b/empty.txt", sha256="3" * 64, size=0),
        row(path="inbox/a/same.txt", sha256="4" * 64, size=9, mtime_utc="2020-01-01T00:00:00Z"),
        row(path="inbox/b/same.txt", sha256="5" * 64, size=9, mtime_utc="2020-01-01T00:00:00Z"),
        row(path="organized/documents/txt/2020/2020-01-01_other.txt", sha256="6" * 64),
    ]
    planned = rules.plan(rows)
    assert planned.deletes == ("inbox/a/.DS_Store", "inbox/a/empty.png", "inbox/a/report.TMP", "inbox/b/empty.txt")
    assert planned.moves == (("inbox/a/same.txt", "organized/documents/txt/2020/2020-01-01_same.txt"), ("inbox/b/same.txt", "organized/documents/txt/2020/2020-01-01_same-2.txt"))
    assert (planned.unique, planned.duplicates, planned.removed) == (2, 0, 4)


def test_plan_orders_collisions_by_mtime_then_path_and_chains_suffixes() -> None:
    rows = [
        row(path="inbox/a/report.pdf", sha256="1" * 64, type="pdf", pdf="D:20190714", mtime_utc="2020-03-03T00:00:00Z"),
        row(path="inbox/b/report (1).pdf", sha256="2" * 64, type="pdf", pdf="D:20190714", mtime_utc="2020-01-01T00:00:00Z"),
        row(path="inbox/c/report-2.pdf", sha256="3" * 64, type="pdf", pdf="D:20190714", mtime_utc="2020-02-02T00:00:00Z"),
        row(path="inbox/d/report.pdf", sha256="4" * 64, type="pdf", pdf="D:20190714", mtime_utc="2020-02-02T00:00:00Z"),
    ]
    planned = rules.plan(rows)
    assert planned.moves == (
        ("inbox/b/report (1).pdf", "organized/documents/pdf/2019/2019-07-14_report.pdf"),
        ("inbox/c/report-2.pdf", "organized/documents/pdf/2019/2019-07-14_report-2.pdf"),
        ("inbox/d/report.pdf", "organized/documents/pdf/2019/2019-07-14_report-3.pdf"),
        ("inbox/a/report.pdf", "organized/documents/pdf/2019/2019-07-14_report-4.pdf"),
    )
    assert [path for _digest, path in planned.expected] == sorted(path for _src, path in planned.moves)


@pytest.mark.parametrize(
    ("path", "problem"),
    [
        ("organized/images/jpg/2019/2019-07-14_img-0042.jpg", None),
        ("organized/images/jpg/2019/2019-07-14_img-0042-2.jpg", None),
        ("organized/other/bin/1999/1999-12-31_file.bin", None),
        ("organized/images/png/2019/2019-07-14_x.jpg", "does not belong"),
        ("organized/images/jpg/2018/2019-07-14_x.jpg", "year folder"),
        ("organized/images/jpg/2019/2019-02-30_x.jpg", "not a real date"),
        ("organized/images/jpg/2019/2019-07-14_X.jpg", "not organized"),
        ("organized/duplicates/x.jpg", "not organized"),
        ("inbox/x.jpg", "not organized"),
        ("organized/images/jpg/2019/2019-07-14_x.jpeg", "does not belong"),
    ],
)
def test_target_problems(path: str, problem: str | None) -> None:
    found = rules.target_problem(path)
    assert (found is None) if problem is None else (problem in found)
