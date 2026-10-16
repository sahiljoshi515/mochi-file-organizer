"""survey: the folder is one the task may name; its rows are the run's state, and before anything is
applied they are exactly the rules' first 60 actions for the folder as it is."""

from pathlib import Path

from .checks import read_state, result, summary_dict
from .layout import folder_problem, look


def verify_input(value):
    problem = folder_problem(value.folder)
    if problem:
        return result(False, problem)
    return result(True, "input is valid")


def rules_rows(found):
    """The rows the rules give a fresh run: (i, path, h, base, drop) for each of the first 60 actions."""
    listed = {step.i for step in found.steps if step.quota}
    rows = []
    for step in found.steps:
        if not step.quota:
            continue
        if step.reason in ("junk", "empty"):
            drop = step.reason
        elif step.reason == "copy" and step.copy_of not in listed:
            drop = "copy"
        else:
            drop = None
        base = None if drop else found.facts[step.i].base
        rows.append((step.i, step.path, step.sha256[: found.hash_length], base, drop))
    return rows


def verify_output(input_value, output_value, workspace):
    state = read_state(workspace)
    if state is None:
        return result(False, "survey left no run state in .file-organizer/state.json")
    if output_value.folder != input_value.folder or state["folder"] != input_value.folder:
        return result(False, "the survey is for another folder")
    given = [(row.i, row.path, row.h, row.base, row.drop.value if row.drop else None) for row in output_value.rows]
    length = state["hash_length"]
    recorded = [(row["i"], row["path"], row["sha256"][:length], row["base"], row["drop"]) for row in state["rows"]]
    if given != recorded:
        return result(False, "the rows differ from the run's recorded rows")
    if summary_dict(output_value.summary) != state["summary"]:
        return result(False, "the summary differs from the run's recorded summary")
    applied = state["applied"]
    moves = sum(entry.get("kind") == "move" for entry in applied)
    deletes = sum(entry.get("kind") == "delete" for entry in applied)
    summary = output_value.summary
    if (summary.moved, summary.deleted, summary.left) != (moves, deletes, len(given) - len(applied)):
        return result(False, "the summary's moved, deleted and left do not match what the run applied")
    if not applied:
        found = look(Path(workspace), input_value.folder)
        if found.refused:
            return result(False, f"the rules refuse this folder, yet survey listed rows: {found.refused}")
        if rules_rows(found) != given:
            return result(False, "the rows are not the rules' first 60 actions for the folder")
        stays = sum(step.action == "stay" for step in found.steps)
        quota = sum(step.quota for step in found.steps)
        want = (len(found.steps), stays, quota, len(found.steps) - stays - quota)
        if (summary.files, summary.stayed, summary.left, summary.remaining) != want:
            return result(False, "the summary's counts are not the folder's")
    return result(True, f"{len(given)} rows listed", rows=len(given))
