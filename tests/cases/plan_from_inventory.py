"""Plans for the scripted harness (~/mochi-dev/harness/scripted_task.py), built from the agent's own
inventory rows with the plugin's rules: the gold plan, or one with a deliberate mistake.

A case's python step loads this file (next to the case) and the plugin's verifier/rules.py, so the
plan is computed exactly as the rules say, from the tool outputs the scripted agent received.
"""

from __future__ import annotations

import importlib.util
import sys
from itertools import pairwise
from pathlib import Path

VARIANTS = (
    "gold",
    "duplicates_moved",  # extra copies moved to organized/duplicates/ instead of deleted
    "near_deleted",  # a file with the same name and size as another deleted as a "duplicate"
    "ext_typing",  # category and extension from the claimed extension, not the content
    "keeper_latest",  # the latest copy kept instead of the earliest
    "collision_by_name",  # collisions numbered by path order instead of (mtime, path)
    "junk_kept",  # junk filed like any other file
    "empty_kept",  # empty files filed like any other file
    "inbox_left",  # the last three moves never made
    "name_date_first",  # a date in the name preferred to the embedded one
)


def load_rules(plugin_dir: Path):
    path = Path(plugin_dir) / "verifier" / "rules.py"
    spec = importlib.util.spec_from_file_location("file_organizer_rules", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["file_organizer_rules"] = module
    spec.loader.exec_module(module)
    return module


def harness_paths() -> tuple[Path, Path]:
    """The plugin folder and the case file, from the harness's command line."""
    words = [word for word in sys.argv[1:] if not word.startswith("-")]
    plugin_dir = next(Path(word) for word in words if (Path(word) / "nanoagent.yaml").is_file())
    case = next(Path(word) for word in words if word.endswith(".json"))
    return plugin_dir.resolve(), case.resolve()


def rows_from(outputs: dict, names: list[str]) -> list[dict]:
    """The inventory rows saved under `names`: inventory pages, or the page unpack_inbox returns."""
    def page_of(block):
        if isinstance(block.get("files"), list):
            return block["files"]
        if isinstance(block.get("inventory"), dict):
            return block["inventory"]["files"]
        return None

    pages = [page_of(outputs[name]) for name in names if name in outputs]
    pages = [page for page in pages if page is not None]
    # Inventory pages start at offset 0, so when there are any they cover unpack_inbox's first page.
    inventory_pages = [page for name in names if name in outputs and isinstance(outputs[name].get("files"), list) for page in [outputs[name]["files"]]]
    rows = []
    for page in inventory_pages or pages:
        rows += page
    return rows


def plan_with(rows: list[dict], rules, variant: str = "gold") -> dict:
    """apply_plan's moves and deletes for `rows` under `variant` (see VARIANTS)."""
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant}")
    rows = sorted((row for row in rows if row["path"].startswith("inbox/")), key=lambda row: row["path"])
    by_path = {row["path"]: row for row in rows}
    near: set[str] = set()
    if variant == "near_deleted":
        seen: dict = {}
        for row in rows:
            key = (rules.file_name(row["path"]), row["size"])
            if key in seen and seen[key]["sha256"] != row["sha256"] and row["size"]:
                near.add(row["path"])
            seen.setdefault(key, row)
    deletes, kept = [], {}
    for row in rows:
        name = rules.file_name(row["path"])
        junk = rules.is_junk(name) and variant != "junk_kept"
        empty = row["size"] == 0 and variant != "empty_kept"
        if junk or empty or row["path"] in near:
            deletes.append(row["path"])
            continue
        best = kept.get(row["sha256"])
        if best is None:
            kept[row["sha256"]] = row
            continue
        mine, theirs = (row["mtime_utc"], row["path"]), (best["mtime_utc"], best["path"])
        better = mine > theirs if variant == "keeper_latest" else mine < theirs
        if better:
            deletes.append(best["path"])
            kept[row["sha256"]] = row
        else:
            deletes.append(row["path"])
    order = (lambda row: row["path"]) if variant == "collision_by_name" else (lambda row: (row["mtime_utc"], row["path"]))
    taken: set[str] = set()
    moves = []
    for row in sorted(kept.values(), key=order):
        typed = rules.Row(**{name: row[name] for name in row if name != "i"})
        kind = typed.type
        if variant == "ext_typing":
            ext = {"jpeg": "jpg", "htm": "html"}.get(typed.ext.lower(), typed.ext.lower())
            kind = ext if ext in rules.CATEGORIES else "bin"
        if variant == "name_date_first":
            date = rules.name_date(rules.file_name(typed.path)) or rules.embedded_date(typed) or typed.mtime_utc[:10]
        else:
            date = rules.file_date(typed)
        base = f"organized/{rules.CATEGORIES[kind]}/{date[:4]}/{date}_{rules.slug(rules.file_name(typed.path))}.{kind}"
        destination, number = base, 1
        while destination in taken:
            number += 1
            destination = rules.with_suffix(base, number)
        taken.add(destination)
        moves.append({"src": typed.path, "dst": destination})
    if variant == "duplicates_moved":
        copies = [path for path in deletes if by_path[path]["sha256"] in kept and by_path[path]["size"] and not rules.is_junk(rules.file_name(path))]
        deletes = [path for path in deletes if path not in copies]
        moves += [{"src": path, "dst": f"organized/duplicates/{index}-{rules.file_name(path)}"} for index, path in enumerate(copies)]
    if variant == "inbox_left":
        moves = moves[:-3]
    numbers = {row["path"]: row["i"] for row in rows}
    return {"moves": [{"i": numbers[move["src"]], "dst": move["dst"]} for move in moves], "deletes": sorted(numbers[path] for path in deletes)}


MOVES_PER_CALL = DELETES_PER_CALL = 80


def batches(plan: dict, count: int) -> list[dict]:
    """`plan` split into exactly `count` apply_plan calls of at most 80 moves and 80 deletes each
    (the last ones may be empty); fails when `count` calls cannot hold it."""
    moves, deletes = plan["moves"], plan["deletes"]
    needed = max(-(-len(moves) // MOVES_PER_CALL), -(-len(deletes) // DELETES_PER_CALL), 1)
    if needed > count:
        raise ValueError(f"the plan needs {needed} apply_plan calls, the case allows {count}")
    return [
        {"moves": moves[index * MOVES_PER_CALL : (index + 1) * MOVES_PER_CALL], "deletes": deletes[index * DELETES_PER_CALL : (index + 1) * DELETES_PER_CALL]}
        for index in range(count)
    ]


def split_by_number(plan: dict, cuts: list[int]) -> list[dict]:
    """`plan` as the batches the instructions prescribe: the moves and deletes of the files numbered
    below the first cut, then from each cut to the next, then from the last cut up (a duplicate's
    keeper and a collision's suffix were decided over the whole plan already)."""
    edges = [0, *cuts, None]
    out = []
    for low, high in pairwise(edges):
        numbers = [move["i"] for move in plan["moves"]] + list(plan["deletes"])
        chosen = {number for number in numbers if number >= low and (high is None or number < high)}
        batch = {"moves": [move for move in plan["moves"] if move["i"] in chosen], "deletes": [number for number in plan["deletes"] if number in chosen]}
        if len(batch["moves"]) > MOVES_PER_CALL or len(batch["deletes"]) > DELETES_PER_CALL:
            raise ValueError("a batch by number holds more than one apply_plan call takes")
        out.append(batch)
    return out


def harness_plan(outputs: dict, names: list[str], variant: str = "gold", count: int = 1, by_number: list[int] | None = None) -> list[dict]:
    """What a case's python step calls: the plan from the saved inventory pages, as `count` batches
    of at most 80 items, or, with `by_number`, as batches split at those file numbers."""
    plugin_dir, _case = harness_paths()
    plan = plan_with(rows_from(outputs, names), load_rules(plugin_dir), variant)
    return split_by_number(plan, by_number) if by_number is not None else batches(plan, count)
