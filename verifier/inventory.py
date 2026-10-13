"""inventory: each page is exactly the rules' own reading of the folder, in path order, and every
file's number is the one the folder's record gives it."""

from pathlib import Path

from .checks import read_ledger, result, root_problem
from .rules import inventory_rows

MAX_LIMIT = 100


def verify_input(value):
    problem = root_problem(value.root)
    if problem:
        return result(False, problem)
    if value.offset < 0:
        return result(False, "offset must be 0 or more")
    if not 1 <= value.limit <= MAX_LIMIT:
        return result(False, f"limit must be 1 to {MAX_LIMIT}")
    return result(True, "input is valid")


def as_tuple(row):
    return (row.path, row.size, row.sha256, row.type, row.ext, row.exif, row.png, row.pdf, row.md, row.mtime_utc)


def verify_output(input_value, output_value, workspace):
    if output_value.root != input_value.root:
        return result(False, "the page is for another folder")
    root = Path(workspace) / input_value.root
    if not root.is_dir():
        return result(False, f"{input_value.root} is not a folder in the workspace")
    rows = inventory_rows(root)
    page = rows[input_value.offset : input_value.offset + input_value.limit]
    following = input_value.offset + input_value.limit
    if output_value.total != len(rows):
        return result(False, f"the folder holds {len(rows)} files, not {output_value.total}")
    if output_value.next != (following if following < len(rows) else None):
        return result(False, "next is not the following page's offset")
    if [as_tuple(row) for row in output_value.files] != [as_tuple(row) for row in page]:
        return result(False, "the page differs from the files on disk as the rules read them")
    numbers = [row.i for row in output_value.files]
    if any(number < 0 for number in numbers) or len(set(numbers)) != len(numbers):
        return result(False, "file numbers must be distinct and 0 or more")
    ledger = read_ledger(workspace, input_value.root)
    if ledger is None:
        return result(False, "the folder's file numbers are not recorded")
    if any(ledger["files"].get(str(row.i)) != row.path for row in output_value.files):
        return result(False, "a file's number differs from the folder's record")
    return result(True, f"{len(page)} of {len(rows)} files, as on disk", files=len(page), total=len(rows))
