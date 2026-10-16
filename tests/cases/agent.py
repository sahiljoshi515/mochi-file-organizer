"""The scripted agent: decides a survey's rows exactly as the organize-folder instructions say (a row with
drop is deleted; a row whose h an earlier kept row has is deleted; any other row moves with n = 1 + the
earlier rows moved with the same base), splits them into calls of 30, and makes the mistakes the wrong
cases need. build_cases.py inlines this file into a case's python step, which then calls
`decide(outputs, folder, mistake)`; the step fills outputs["batch0"], ["batch1"] (and ["fix"]).
"""


def plan_rows(rows):
    """[(row, action, n)] for the rows, in order, by the instructions."""
    decided, kept_h, moved_per_base = [], set(), {}
    for row in rows:
        if row["drop"] or row["h"] in kept_h:
            decided.append((row, "delete", None))
            continue
        kept_h.add(row["h"])
        moved_per_base[row["base"]] = moved_per_base.get(row["base"], 0) + 1
        decided.append((row, "move", moved_per_base[row["base"]]))
    return decided


def calls(folder, decided, size=30):
    """The decisions as apply inputs: the first `size` rows, then the rest."""
    batches = []
    for part in (decided[:size], decided[size:]):
        batches.append(
            {
                "folder": folder,
                "moves": [{"i": row["i"], "n": n} for row, action, n in part if action == "move"],
                "deletes": [row["i"] for row, action, _n in part if action == "delete"],
            }
        )
    return batches


def keeper_wrong(decided):
    """Keep the last copy of duplicated bytes instead of the first."""
    groups = {}
    for index, (row, _action, _n) in enumerate(decided):
        if not row["drop"]:
            groups.setdefault(row["h"], []).append(index)
    swapped = list(decided)
    for indexes in groups.values():
        # a group whose last copy files elsewhere than its first (other slug or date), so the mistake shows
        if len(indexes) > 1 and decided[indexes[-1]][0]["base"] != decided[indexes[0]][0]["base"]:
            first, last = indexes[0], indexes[-1]
            swapped[first] = (decided[first][0], "delete", None)
            last_row = decided[last][0]
            same_base = sum(1 for row, action, _n in swapped[:last] if action == "move" and row["base"] == last_row["base"])
            swapped[last] = (last_row, "move", same_base + 1)
            return swapped
    raise RuntimeError("no duplicated bytes filed elsewhere by another copy: keeper_wrong needs one")


def duplicate_kept(decided):
    """Move a duplicate copy as well, as if it were a file of its own."""
    seen = set()
    for index, (row, action, _n) in enumerate(decided):
        if row["drop"]:
            continue
        if row["h"] in seen and action == "delete":
            same_base = sum(1 for other, act, _x in decided[:index] if act == "move" and other["base"] == row["base"])
            changed = list(decided)
            changed[index] = (row, "move", same_base + 1)
            return changed
        seen.add(row["h"])
    raise RuntimeError("no duplicate copy among the rows: duplicate_kept needs one")


def rank_swapped(decided):
    """Two files that share a base get each other's numbers."""
    by_base = {}
    for index, (row, action, _n) in enumerate(decided):
        if action == "move":
            by_base.setdefault(row["base"], []).append(index)
    for indexes in by_base.values():
        if len(indexes) >= 2:
            first, second = indexes[0], indexes[1]
            changed = list(decided)
            changed[first] = (decided[first][0], "move", decided[second][2])
            changed[second] = (decided[second][0], "move", decided[first][2])
            return changed
    raise RuntimeError("no two moves share a base: rank_swapped needs a collision")


def junk_as_move(decided):
    for index, (row, _action, _n) in enumerate(decided):
        if row["drop"] in ("junk", "empty"):
            changed = list(decided)
            changed[index] = (row, "move", 1)
            return changed
    raise RuntimeError("no junk or empty row: junk_as_move needs one")


def decide(outputs, folder, mistake=None):
    rows = outputs["survey"]["rows"]
    decided = plan_rows(rows)
    if mistake == "keeper_wrong":
        decided = keeper_wrong(decided)
    elif mistake == "duplicate_kept":
        decided = duplicate_kept(decided)
    elif mistake == "rank_swapped":
        decided = rank_swapped(decided)
    elif mistake in ("junk_as_move", "fix_errors"):
        decided = junk_as_move(decided)
    batch0, batch1 = calls(folder, decided)
    if mistake == "skipped_batch":
        batch1 = {"folder": folder, "moves": [], "deletes": []}
    if mistake == "out_of_quota":
        # one quota row is swapped for a number outside the run's rows: refused, so that row is left
        beyond = max([row["i"] for row in rows] + [0]) + 1
        if batch0["moves"]:
            batch0["moves"][0] = {"i": beyond, "n": 1}
        else:
            batch0["deletes"][0] = beyond
    outputs["batch0"], outputs["batch1"] = batch0, batch1
    if mistake == "fix_errors":
        # the one refused item, done right in a third call
        wrong = next(row for row, _action, _n in decided if row["drop"] in ("junk", "empty"))
        outputs["fix"] = {"folder": folder, "moves": [], "deletes": [wrong["i"]]}
