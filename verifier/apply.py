"""apply: shapes on the way in; on the way out, every move and delete it did not report as refused
happened on disk exactly as the run's log records it, and its summary adds up."""

import hashlib
import re
from pathlib import Path

from .checks import read_state, result, summary_dict
from .layout import folder_problem, resolve
from .naming import path_key
from .plan import MAX_NUMBER, nth_free
from .walk import scan

ITEM_LIMIT = 60
ERROR = re.compile(r"^(move|delete) (-?[0-9]+): ")


def verify_input(value):
    problem = folder_problem(value.folder)
    if problem:
        return result(False, problem)
    if len(value.moves) + len(value.deletes) > ITEM_LIMIT:
        return result(False, f"at most {ITEM_LIMIT} moves and deletes per call")
    numbers = [move.i for move in value.moves] + list(value.deletes)
    if any(number < 0 for number in numbers):
        return result(False, "row numbers are 0 or more")
    if len(set(numbers)) != len(numbers):
        return result(False, "a row is named twice in one call")
    if any(not 1 <= move.n <= MAX_NUMBER for move in value.moves):
        return result(False, f"n must be 1 to {MAX_NUMBER}")
    return result(True, "input is valid")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_output(input_value, output_value, workspace):
    state = read_state(workspace)
    if state is None or state["folder"] != input_value.folder:
        return result(False, "apply left no run state for this folder in .file-organizer/state.json")
    root, problem = resolve(Path(workspace), input_value.folder)
    if root is None:
        return result(False, problem)
    items = {("move", move.i) for move in input_value.moves} | {("delete", i) for i in input_value.deletes}
    refused = set()
    for line in output_value.errors:
        found = ERROR.match(line)
        if not found or (found.group(1), int(found.group(2))) not in items:
            return result(False, f"an error names no item of this call: {line[:120]}")
        refused.add((found.group(1), int(found.group(2))))
    rows = {row["i"]: row for row in state["rows"]}
    this_call = [entry for entry in state["applied"] if entry.get("call") == state.get("calls")]
    log = {entry["i"]: entry for entry in this_call}
    for kind, i in refused:
        if i in log and log[i].get("kind") == kind:
            return result(False, f"{kind} {i} is reported refused, yet this call did it")
    taken = {path_key(path) for path in state["taken"]}
    held = None
    done = 0
    for i in input_value.deletes:
        if ("delete", i) in refused:
            continue
        entry, row = log.get(i), rows.get(i)
        if entry is None or row is None or entry.get("kind") != "delete":
            return result(False, f"row {i}'s delete reported no error but is not in the run's log")
        if root.joinpath(entry["path"]).is_file():
            return result(False, f"row {i} ({entry['path']}) is still there although its delete reported no error")
        if row["drop"] is None:
            if held is None:
                held = {digest(root / path) for path in scan(Path(workspace), root).files}
            if row["sha256"] not in held:
                return result(False, f"row {i} was the last copy of its bytes and was deleted")
        done += 1
    for move in input_value.moves:
        if ("move", move.i) in refused:
            continue
        entry, row = log.get(move.i), rows.get(move.i)
        if entry is None or row is None or entry.get("kind") != "move" or entry.get("n") != move.n:
            return result(False, f"row {move.i}'s move reported no error but is not in the run's log")
        if row["drop"] is not None or row["base"] is None:
            return result(False, f"row {move.i} has drop {row['drop']} yet was moved")
        wanted = nth_free(row["base"], row["ext"], taken, move.n)
        if entry.get("to") != wanted:
            return result(False, f"row {move.i} went to {entry.get('to')}, but n {move.n} names {wanted}")
        target = root.joinpath(wanted)
        if not target.is_file() or target.is_symlink() or digest(target) != row["sha256"]:
            return result(False, f"row {move.i} is not at {wanted} with its bytes although its move reported no error")
        if root.joinpath(entry["from"]).is_file():
            return result(False, f"row {move.i} is still at {entry['from']} as well")
        done += 1
    if output_value.applied != done or len(this_call) != done:
        return result(False, f"applied says {output_value.applied}, but {len(this_call)} items were done by this call")
    if summary_dict(output_value.summary) != state["summary"]:
        return result(False, "the summary differs from the run's recorded summary")
    moves = sum(entry.get("kind") == "move" for entry in state["applied"])
    deletes = sum(entry.get("kind") == "delete" for entry in state["applied"])
    summary = output_value.summary
    if (summary.moved, summary.deleted, summary.left) != (moves, deletes, len(rows) - len(state["applied"])):
        return result(False, "the summary's moved, deleted and left do not match the run's log")
    return result(True, f"{done} done, {len(refused)} refused", done=done, refused=len(refused))
