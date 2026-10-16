"""Name rules (RULES.md §1, §3 step 2, §4): junk and hidden names, claimed extensions, dates in names,
slugs, the scheme form and base paths, plus the calendar arithmetic every date rule shares.

Shared, byte for byte, by src/plugin/ and verifier/ (a test asserts it): it imports only what a
verifier may, and computes dates by arithmetic, without datetime.
"""

from __future__ import annotations

import re
import unicodedata

ORGANIZED = "organized"
UNDATED = "undated"
JUNK_NAMES = frozenset({".ds_store", "thumbs.db", "ehthumbs.db", "ehthumbs_vista.db", "desktop.ini", "icon\r"})
JUNK_PREFIXES = ("._", "~$", ".~lock.")
JUNK_EXTS = frozenset({"tmp", "part", "crdownload"})
CLAIMED = re.compile(r"^(.+)\.([A-Za-z0-9]{1,10})$")
NAME_DATE = re.compile(r"(?<![0-9])([0-9]{4})([-_.]?)([0-9]{2})\2([0-9]{2})(?![0-9])")
SCHEME = re.compile(
    r"^([0-9]{4}-[0-9]{2}-[0-9]{2}|undated)_([a-z0-9]+(?:-[a-z0-9]+)*)(?:_([2-9]|[1-9][0-9]+))?\.(tar\.gz|[a-z0-9]{1,10})$"
)
COPY_PREFIX = re.compile(r"^copy of ")
COPY_SUFFIX = re.compile(r"(\s*\([0-9]+\)|\s+-\s+copy(\s+\([0-9]+\))?|\s+copy(\s+[0-9]+)?|[_-]copy[0-9]*)$")
NOT_SLUG = re.compile(r"[^a-z0-9]+")
SLUG_LIMIT = 60
EMPTY_SLUG = "file"
NAME_YEARS = (1990, 2039)
EMBEDDED_YEARS = (1971, 2099)


# ----- Calendar arithmetic (proleptic Gregorian) -----


def is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def days_in_month(year: int, month: int) -> int:
    if month == 2:
        return 29 if is_leap(year) else 28
    return 30 if month in (4, 6, 9, 11) else 31


def real_date(year: int, month: int, day: int, years: tuple[int, int]) -> str | None:
    """`YYYY-MM-DD` when the numbers are a calendar date inside `years` (inclusive), else None."""
    if not years[0] <= year <= years[1] or not 1 <= month <= 12 or not 1 <= day <= days_in_month(year, month):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def civil(days: int) -> tuple[int, int, int]:
    """The calendar date `days` after 1970-01-01 (Howard Hinnant's algorithm)."""
    days += 719468
    era = days // 146097
    doe = days - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    day = doy - (153 * mp + 2) // 5 + 1
    month = mp + 3 if mp < 10 else mp - 9
    return yoe + era * 400 + (1 if month <= 2 else 0), month, day


# ----- Names -----


def claimed_ext(name: str) -> str:
    """The 1 to 10 ASCII letters and digits after the last `.`, lowercased, unless that `.` starts the name."""
    found = CLAIMED.match(name)
    return found.group(2).lower() if found else ""


def is_junk(name: str) -> bool:
    lower = name.lower()
    return lower in JUNK_NAMES or lower.startswith(JUNK_PREFIXES) or claimed_ext(name) in JUNK_EXTS


def is_hidden(name: str) -> bool:
    """A name the rules leave alone; junk is checked first, so `.DS_Store` is junk, not hidden."""
    return name.startswith(".") and not is_junk(name)


def stem_of(name: str, ext: str) -> str:
    """The name without its extension: without `.tar.gz` or `.tgz` for a `tar.gz`, else without the claimed one."""
    lower = name.lower()
    if ext == "tar.gz":
        for tail in (".tar.gz", ".tgz"):
            if lower.endswith(tail) and len(name) > len(tail):
                return name[: -len(tail)]
    found = CLAIMED.match(name)
    return found.group(1) if found else name


def scheme(name: str) -> tuple[str | None, str] | None:
    """For a name in scheme form, its date (None for `undated` or a date the rules do not accept) and slug."""
    found = SCHEME.match(name)
    if not found:
        return None
    date = None
    if found.group(1) != UNDATED:
        year, month, day = (int(part) for part in found.group(1).split("-"))
        date = real_date(year, month, day, EMBEDDED_YEARS)
    return date, found.group(2)


def name_date(stem: str) -> tuple[str, int, int] | None:
    """The first real `YYYY?MM?DD` date in `stem`, with its span, or None (RULES §3 step 2)."""
    for found in NAME_DATE.finditer(stem):
        date = real_date(int(found.group(1)), int(found.group(3)), int(found.group(4)), NAME_YEARS)
        if date:
            return date, found.start(), found.end()
    return None


def slug_of(stem: str) -> str:
    """RULES §4: the slug of a name that is not in scheme form, from its stem."""
    dated = name_date(stem)
    text = stem[: dated[1]] + stem[dated[2] :] if dated else stem
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    while COPY_PREFIX.match(text):
        text = COPY_PREFIX.sub("", text, count=1)
    while True:
        stripped = COPY_SUFFIX.sub("", text, count=1)
        if stripped == text:
            break
        text = stripped
    text = NOT_SLUG.sub("-", text).strip("-")
    text = text[:SLUG_LIMIT].rstrip("-")
    return text or EMPTY_SLUG


def name_facts(name: str, ext: str) -> tuple[str | None, str]:
    """The date a name gives (RULES §3 step 2) and its slug (RULES §4)."""
    schemed = scheme(name)
    if schemed is not None:
        return schemed
    stem = stem_of(name, ext)
    dated = name_date(stem)
    return (dated[0] if dated else None), slug_of(stem)


def base_path(group: str, kind: str, ext: str, date: str | None, slug: str) -> str:
    """organized/<group>/<type>/<YYYY>/<YYYY-MM-DD>_<slug>.<ext>, or the undated form."""
    if date is None:
        return f"{ORGANIZED}/{group}/{kind}/{UNDATED}/{UNDATED}_{slug}.{ext}"
    return f"{ORGANIZED}/{group}/{kind}/{date[:4]}/{date}_{slug}.{ext}"


def suffixed(base: str, ext: str, number: int) -> str:
    """`base` with `_<number>` before its extension; number 1 is the base itself."""
    if number == 1:
        return base
    return f"{base[: -len(ext) - 1]}_{number}.{ext}"


def conforms(path: str, base: str, ext: str) -> bool:
    """Whether `path` is `base`, or `base` with `_<n>` (n >= 2, no leading zero) before the extension."""
    if path == base:
        return True
    head, tail = base[: -len(ext) - 1] + "_", "." + ext
    if not (path.startswith(head) and path.endswith(tail)) or len(path) <= len(head) + len(tail):
        return False
    number = path[len(head) : -len(tail)]
    return re.fullmatch(r"[2-9]|[1-9][0-9]+", number) is not None


def path_key(path: str) -> str:
    """A path as the rules compare taken paths: ignoring letter case and Unicode normalization."""
    return unicodedata.normalize("NFD", unicodedata.normalize("NFD", path).casefold())
