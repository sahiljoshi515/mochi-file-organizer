"""apply_plan: shapes on the way in; on the way out, every item it did not report as failed has
happened on disk, as the folder's numbers record shows."""

from pathlib import Path

from .checks import read_ledger, relative_problem, result, root_problem
from .rules import ORGANIZED

MAX_MOVES = 80
MAX_DELETES = 80


def destination_problem(path):
    problem = relative_problem("dst", path)
    if problem:
        return problem
    if not path.startswith(ORGANIZED + "/"):
        return f"dst must be a file path under {ORGANIZED}/"
    return None


def verify_input(value):
    problem = root_problem(value.root)
    if problem:
        return result(False, problem)
    if len(value.moves) > MAX_MOVES or len(value.deletes) > MAX_DELETES:
        return result(False, f"at most {MAX_MOVES} moves and {MAX_DELETES} deletes per call: apply the plan in batches")
    numbers = [move.i for move in value.moves] + list(value.deletes)
    if any(number < 0 for number in numbers):
        return result(False, "file numbers are 0 or more")
    if len(set(numbers)) != len(numbers):
        return result(False, "a file number is used twice")
    for move in value.moves:
        problem = destination_problem(move.dst)
        if problem:
            return result(False, problem)
    destinations = [move.dst for move in value.moves]
    if len(set(destinations)) != len(destinations):
        return result(False, "two moves share a destination")
    return result(True, "input is valid")


def failed(errors, label):
    """Whether an error line is about the item the tool labels `label`."""
    return any(line.startswith(label) for line in errors)


def verify_output(input_value, output_value, workspace):
    root = Path(workspace) / input_value.root
    if not root.is_dir():
        return result(False, f"{input_value.root} is not a folder in the workspace")
    ledger = read_ledger(workspace, input_value.root)
    if ledger is None:
        return result(False, "the folder's file numbers are not recorded")
    applied_moves = applied_deletes = 0
    for move in input_value.moves:
        if failed(output_value.errors, f"move {move.i} -> {move.dst}:"):
            continue
        applied_moves += 1
        if ledger["files"].get(str(move.i)) != move.dst or not (root / move.dst).is_file():
            return result(False, f"file {move.i} is not at {move.dst} although its move reported no error")
    for number in input_value.deletes:
        if failed(output_value.errors, f"delete {number}:"):
            continue
        applied_deletes += 1
        gone = ledger["deleted"].get(str(number))
        if gone is None or (root / gone).exists():
            return result(False, f"file {number} still exists although its deletion reported no error")
    if output_value.moved != applied_moves or output_value.deleted != applied_deletes:
        return result(False, "the counts of applied moves and deletes do not match the errors reported")
    if output_value.removed_dirs < 0:
        return result(False, "a count is negative")
    return result(True, f"{output_value.moved} moved, {output_value.deleted} deleted", errors=len(output_value.errors))
