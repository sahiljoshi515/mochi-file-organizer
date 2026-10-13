"""list_tree: a sorted, bounded listing of the folder."""

from pathlib import Path

from .checks import result, root_problem
from .rules import files_under

MAX_ENTRIES = 200


def verify_input(value):
    problem = root_problem(value.root)
    if problem:
        return result(False, problem)
    if not 1 <= value.max_entries <= MAX_ENTRIES:
        return result(False, f"max_entries must be 1 to {MAX_ENTRIES}")
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    if output_value.root != input_value.root:
        return result(False, "the listing is for another folder")
    root = Path(workspace) / input_value.root
    if not root.is_dir():
        return result(False, f"{input_value.root} is not a folder in the workspace")
    entries = output_value.entries
    if entries != sorted(entries) or len(set(entries)) != len(entries):
        return result(False, "entries are not sorted and distinct")
    if len(entries) > input_value.max_entries:
        return result(False, f"more than {input_value.max_entries} entries")
    files = len(files_under(root))
    if output_value.files != files:
        return result(False, f"the folder holds {files} files, not {output_value.files}")
    return result(True, f"{len(entries)} entries", files=files, dirs=output_value.dirs)
