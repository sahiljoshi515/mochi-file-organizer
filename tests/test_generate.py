from __future__ import annotations

import collections
from pathlib import Path

import pytest

from plugin import generate, rules


def digest(root: Path) -> list[tuple[str, str, int]]:
    return [(row.path, row.sha256, (root / row.path).stat().st_mtime_ns) for row in rules.inventory_rows(root)]


def test_the_same_seed_and_size_give_the_same_tree(tmp_path: Path) -> None:
    first, second = tmp_path / "one", tmp_path / "two"
    assert generate.generate(first, 7, "small") == generate.generate(second, 7, "small")
    assert digest(first) == digest(second)
    assert all(mtime % 1_000_000_000 == 0 for _path, _digest, mtime in digest(first))
    specs, dirs = generate.build(7, "small")
    assert [(spec.path, spec.data, spec.mtime) for spec in specs] == [(spec.path, spec.data, spec.mtime) for spec in generate.build(7, "small")[0]]
    assert sorted(spec.path for spec in specs) == [path for path, _digest, _mtime in digest(first)]
    assert all((first / rules.INBOX / folder).is_dir() for folder in dirs)


def test_different_seeds_give_different_files(tmp_path: Path) -> None:
    def kept(root: Path) -> set[str]:
        return {row.sha256 for row in rules.inventory_rows(root) if row.size and not rules.is_junk(rules.file_name(row.path))}

    assert kept(generate_into(tmp_path / "a", 1, "small")).isdisjoint(kept(generate_into(tmp_path / "b", 2, "small")))


def test_paths_are_distinct_on_every_filesystem() -> None:
    for seed, size in [(1, "small"), (1, "medium"), (2, "large"), (3, "large")]:
        specs, dirs = generate.build(seed, size)
        keys = [generate.Maker.key(spec.path) for spec in specs]
        assert len(set(keys)) == len(keys), "no two paths differ only by case or normalization"
        folders = {generate.Maker.key(f"inbox/{folder}") for folder in dirs if folder}
        assert folders.isdisjoint(keys), "no file is named like a folder"


def generate_into(root: Path, seed: int, size: str) -> Path:
    generate.generate(root, seed, size)
    return root


@pytest.mark.parametrize("size", ["small", "medium", "large"])
def test_sizes_and_composition(tmp_path: Path, size: str) -> None:
    root = generate_into(tmp_path / size, 3, size)
    rows = rules.inventory_rows(root)
    total = rules.COUNTS[size]
    assert len(rows) == total
    planned = rules.plan(rows)
    assert planned.duplicates == round(0.25 * total)
    assert planned.removed == round(0.06 * total) + round(0.03 * total)
    assert planned.unique == total - planned.duplicates - planned.removed
    dirs = [path for path in (root / rules.INBOX).rglob("*") if path.is_dir()]
    assert 8 <= len(dirs) <= 25
    assert max(len(path.relative_to(root / rules.INBOX).parts) for path in dirs) <= 4
    assert any(not any(child.is_file() for child in path.rglob("*")) for path in dirs), "some folders stay empty"
    assert len({row.mtime_utc for row in rows}) >= total - 4, "mtimes are distinct but for the deliberate ties"


def test_every_kind_appears_and_sniffs_as_made() -> None:
    specs, _dirs = generate.build(1, "large")
    kinds = collections.Counter(spec.kind for spec in specs)
    assert set(generate.KINDS) <= set(kinds)
    for spec in specs:
        if spec.data and not rules.is_junk(rules.file_name(spec.path)):
            assert rules.sniff(spec.data) == spec.kind, spec.path


def test_the_traps_are_present(tmp_path: Path) -> None:
    root = generate_into(tmp_path / "root", 1, "small")
    rows = rules.inventory_rows(root)
    by_hash = collections.defaultdict(list)
    for row in rows:
        by_hash[row.sha256].append(row)
    groups = [group for group in by_hash.values() if len(group) > 1 and group[0].size]
    assert groups, "duplicate groups"
    keepers = [min(group, key=lambda row: (row.mtime_utc, row.path)) for group in groups]
    assert any(keeper.path != min(group, key=lambda row: row.path).path for keeper, group in zip(keepers, groups, strict=True)), "a keeper that is not the first by name"
    assert any(len({row.mtime_utc for row in group}) < len(group) for group in groups), "a tie in a duplicate group"
    names = collections.Counter((rules.file_name(row.path), row.size) for row in rows if row.size)
    near = [key for key, count in names.items() if count > 1 and len({row.sha256 for row in rows if (rules.file_name(row.path), row.size) == key}) > 1]
    assert near, "near-duplicates: same name and size, different bytes"
    assert any(row.ext and row.ext.lower() not in (row.type, "jpeg", "htm") for row in rows), "misnamed files"
    assert any(row.ext == "" for row in rows if row.size), "files without an extension"
    assert any(row.ext.isupper() for row in rows if row.ext), "upper-case extensions"
    assert any(row.exif and rules.name_date(rules.file_name(row.path)) and rules.name_date(rules.file_name(row.path)) != rules.embedded_date(row) for row in rows), "a name date that disagrees with EXIF"
    assert any(rules.NAME_DATE.search(rules.file_name(row.path)) and not rules.name_date(rules.file_name(row.path)) for row in rows), "an invalid date in a name"
    assert any(row.size == 0 for row in rows), "empty files"
    assert any(rules.is_junk(rules.file_name(row.path)) and row.type == "jpg" for row in rows), "a .tmp that is really a JPEG"
    assert any(not rules.file_name(row.path).isascii() for row in rows), "names with accents or other scripts"
    planned = rules.plan(rows)
    assert any(dst.endswith("-2." + dst.rsplit(".", 1)[1]) for _src, dst in planned.moves), "a collision suffix"
    kept = {src for src, _dst in planned.moves}
    by_base = collections.defaultdict(list)
    for row in rows:
        if row.path in kept:
            by_base[rules.target(row)].append(row)
    assert any(
        sorted(group, key=lambda row: row.path) != sorted(group, key=lambda row: (row.mtime_utc, row.path))
        for group in by_base.values()
        if len(group) > 1
    ), "a collision whose path order differs from its mtime order"
