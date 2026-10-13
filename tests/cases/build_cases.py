"""Writes the scripted cases next to this file: gold cases per size and one case per deliberate
mistake (see plan_from_inventory.VARIANTS). The small cases follow the hosted path exactly:
unpack_inbox (which returns the inventory), then apply_plan by number ranges (gold_small: three
calls for i 0-14, 15-29, 30-44; gold_small_one_call: everything at once). The large case also
exercises read_rules, inventory and list_tree. Run: python tests/cases/build_cases.py"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
STEP = (
    "import importlib.util, sys\n"
    "from pathlib import Path\n"
    "words = [w for w in sys.argv[1:] if not w.startswith('-')]\n"
    "case = next(Path(w) for w in words if w.endswith('.json')).resolve()\n"
    "spec = importlib.util.spec_from_file_location('plan_from_inventory', case.parent / 'plan_from_inventory.py')\n"
    "helper = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(helper)\n"
    "for index, batch in enumerate(helper.harness_plan(outputs, ['start', 'inv0', 'inv1', 'inv2'], {variant!r}, {batches}, {by_number})):\n"
    "    outputs[f'batch{{index}}'] = batch\n"
)
EXPECT = {
    "gold": {"valid": True, "score_min": 1.0},
    "duplicates_moved": {"valid": False, "message_contains": "duplicate"},
    "near_deleted": {"valid": False, "message_contains": "missing"},
    "ext_typing": {"valid": False, "message_contains": "misplaced"},
    "keeper_latest": {"valid": False, "message_contains": "misplaced"},
    "collision_by_name": {"valid": False, "message_contains": "misplaced"},
    "junk_kept": {"valid": False, "message_contains": "other file"},
    "empty_kept": {"valid": False, "message_contains": "other file"},
    "inbox_left": {"valid": False, "message_contains": "left outside"},
    "name_date_first": {"valid": False, "message_contains": "misplaced"},
}
PAGE = 100
# inventory calls after unpack_inbox's own first page: none for small; medium and large page on.
PAGES = {"small": 0, "medium": 2, "large": 3}
# apply_plan calls per case: each takes at most 80 moves and 80 deletes; a small plan fits one.
BATCHES = {"small": 1, "medium": 2, "large": 3}
# The hosted path for small: three calls, for the files numbered 0-14, 15-29 and 30-44.
SMALL_CUTS = [15, 30]


def case(seed: int, size: str, variant: str, by_number: list[int] | None = None) -> dict:
    steps = [{"tool": "unpack_inbox", "arguments": {"seed": seed, "size": size}, "save_as": "start"}]
    if size == "large":
        steps.append({"tool": "read_rules", "arguments": {}})
    for page in range(PAGES[size]):
        steps.append({"tool": "inventory", "arguments": {"root": "$ref:start.root", "offset": PAGE * page, "limit": PAGE}, "save_as": f"inv{page}"})
    count = len(by_number) + 1 if by_number is not None else BATCHES[size]
    steps.append({"python": STEP.format(variant=variant, batches=count, by_number=by_number)})
    for batch in range(count):
        steps.append({"tool": "apply_plan", "arguments": {"root": "$ref:start.root", "moves": f"$ref:batch{batch}.moves", "deletes": f"$ref:batch{batch}.deletes"}, "save_as": f"applied{batch}"})
    if size == "large":
        steps.append({"tool": "list_tree", "arguments": {"root": "$ref:start.root", "max_entries": 200}})
    answer = {
        "gold": "Deleted every junk, empty and duplicate file and moved every other file to organized/ by the rules.",
    }.get(variant, f"Tidied the folder ({variant.replace('_', ' ')}).")
    return {"task": "organize", "arguments": {"seed": seed, "size": size}, "steps": steps, "answer": answer, "expect": EXPECT[variant]}


def main() -> None:
    cases = {
        "gold_small": case(1, "small", "gold", by_number=SMALL_CUTS),
        "gold_small_one_call": case(1, "small", "gold"),
        "gold_medium": case(1, "medium", "gold"),
        "gold_large": case(2, "large", "gold"),
    }
    for variant in EXPECT:
        if variant != "gold":
            cases[f"wrong_{variant}"] = case(1, "small", variant)
    for name, content in cases.items():
        (HERE / f"{name}.json").write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")
        print("wrote", name)


if __name__ == "__main__":
    main()
