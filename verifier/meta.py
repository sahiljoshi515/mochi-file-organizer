"""RULES.md §3 step 1: the date embedded in a file, by type. Shared, byte for byte, by src/plugin/ and
verifier/. Every reader gives (source, raw value as stored, YYYY-MM-DD) or None; a value that is not a
real date with a year from 1971 to 2099 gives None, and the rules move on.
"""

from __future__ import annotations

import re

from .formats import (
    cr3_dates_original,
    front_matter_date,
    heif_exif,
    jpeg_exif,
    mvhd_seconds,
    pdf_creation,
    png_chunks,
    riff_chunks,
    tiff_date_original,
    zip_member,
)
from .naming import EMBEDDED_YEARS, civil, real_date

EXIF = "exif"
PNG_TEXT = "png-text"
PDF = "pdf"
OFFICE = "office"
ODF = "odf"
MVHD = "mvhd"
FRONT_MATTER = "front-matter"
EXIF_DATE = re.compile(r"([0-9]{4}):([0-9]{2}):([0-9]{2})")
ISO_DATE = re.compile(r"\s*([0-9]{4})-([0-9]{2})-([0-9]{2})")
RFC_DATE = re.compile(r"\s*(?:[A-Za-z]{3},\s*)?([0-9]{1,2})\s+([A-Za-z]{3})\s+([0-9]{4})")
PDF_DATE = re.compile(r"(?:D:)?([0-9]{4})([0-9]{2})([0-9]{2})")
CORE_CREATED = re.compile(r"<dcterms:created(?:\s[^<>]*+)?>")
ODF_CREATED = re.compile(r"<meta:creation-date(?:\s[^<>]*+)?>")
LEADING_DATE = re.compile(r"\s*([0-9]{4})-([0-9]{2})-([0-9]{2})")
FRONT_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
MONTHS = {name: index for index, name in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
SECONDS_1904_TO_1970 = 2082844800
OOXML = frozenset(["docx", "docm", "dotx", "dotm", "xlsx", "xlsm", "xltx", "xltm", "xlam", "xlsb", "pptx", "pptm", "potx", "potm", "ppsx", "ppsm", "ppam"])
ODF_KINDS = frozenset({"odt", "ods", "odp"})
SEARCHED = frozenset({"heic", "avif"})
ISO_MEDIA = frozenset({"mp4", "mov", "m4a"})

Found = tuple[str, str, str]


def dated(source: str, raw: str, found: re.Match | None) -> Found | None:
    if found is None:
        return None
    date = real_date(int(found.group(1)), int(found.group(2)), int(found.group(3)), EMBEDDED_YEARS)
    return (source, raw, date) if date else None


def exif_date(tiff: bytes | None) -> Found | None:
    return exif_value(tiff_date_original(tiff) if tiff else None)


def exif_value(raw: str | None) -> Found | None:
    return dated(EXIF, raw, EXIF_DATE.match(raw)) if raw is not None else None


def png_date(data: bytes) -> Found | None:
    chunks = png_chunks(data)
    for kind, body in chunks:
        if kind == b"eXIf":
            found = exif_date(body[6:] if body.startswith(b"Exif\x00\x00") else body)
            if found:
                return found
            break
    for kind, body in chunks:
        if kind == b"tEXt":
            keyword, _sep, text = body.partition(b"\x00")
            if keyword == b"Creation Time":
                raw = text.decode("latin-1")
                found = dated(PNG_TEXT, raw, ISO_DATE.match(raw))
                if found:
                    return found
                rfc = RFC_DATE.match(raw)
                if rfc and rfc.group(2).lower() in MONTHS:
                    date = real_date(int(rfc.group(3)), MONTHS[rfc.group(2).lower()], int(rfc.group(1)), EMBEDDED_YEARS)
                    return (PNG_TEXT, raw, date) if date else None
                return None
    return None


def webp_date(data: bytes) -> Found | None:
    for fourcc, body in riff_chunks(data):
        if fourcc == b"EXIF":
            return exif_date(body[6:] if body.startswith(b"Exif\x00\x00") else body)
    return None


def zipped_date(data: bytes, member: str, source: str, element: re.Pattern) -> Found | None:
    """The leading date of the first `element`'s text in the zip entry `member`."""
    content = zip_member(data, member)
    if content is None:
        return None
    text = content.decode("utf-8", "replace")
    opening = element.search(text)
    if opening is None:
        return None
    found = LEADING_DATE.match(text, opening.end())
    return dated(source, found.group(0).strip(), found) if found else None


def media_date(data: bytes) -> Found | None:
    seconds = mvhd_seconds(data)
    if seconds is None:
        return None
    year, month, day = civil((seconds - SECONDS_1904_TO_1970) // 86400)
    date = real_date(year, month, day, EMBEDDED_YEARS)
    return (MVHD, str(seconds), date) if date else None


def embedded(kind: str, ext: str, data: bytes, text: str | None) -> Found | None:
    """(source, raw, date) for the date embedded in a file of `kind` (its type) with extension `ext`, or None."""
    if kind == "jpg":
        return exif_date(jpeg_exif(data))
    if kind == "tiff" or (kind == "raw" and data[:4] in (b"II*\x00", b"MM\x00*")):
        return exif_date(data)
    if kind in SEARCHED:
        return exif_date(heif_exif(data))
    if kind == "raw" and ext == "cr3":
        return next((found for found in map(exif_value, cr3_dates_original(data)) if found), None)
    if kind == "webp":
        return webp_date(data)
    if kind == "png":
        return png_date(data)
    if kind == "pdf":
        raw = pdf_creation(data)
        return dated(PDF, raw, PDF_DATE.match(raw)) if raw is not None else None
    if kind in OOXML:
        return zipped_date(data, "docProps/core.xml", OFFICE, CORE_CREATED)
    if kind in ODF_KINDS:
        return zipped_date(data, "meta.xml", ODF, ODF_CREATED)
    if kind in ISO_MEDIA:
        return media_date(data)
    if kind == "md" and text is not None:
        raw = front_matter_date(text)
        return None if raw is None else dated(FRONT_MATTER, raw, FRONT_DATE.match(raw))
    return None
