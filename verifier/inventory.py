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


def page_problem(root_name, offset, limit, page, workspace):
    """What is wrong with `page` (an InventoryOutput) as the rows `offset`..`offset+limit` of the
    folder `root_name`, or None; (problem, shown, total) with the counts."""
    if page.root != root_name:
        return "the page is for another folder", 0, 0
    root = Path(workspace) / root_name
    if not root.is_dir():
        return f"{root_name} is not a folder in the workspace", 0, 0
    rows = inventory_rows(root)
    expected = rows[offset : offset + limit]
    following = offset + limit
    if page.total != len(rows):
        return f"the folder holds {len(rows)} files, not {page.total}", 0, len(rows)
    if page.next != (following if following < len(rows) else None):
        return "next is not the following page's offset", 0, len(rows)
    if [as_tuple(row) for row in page.files] != [as_tuple(row) for row in expected]:
        return "the page differs from the files on disk as the rules read them", 0, len(rows)
    numbers = [row.i for row in page.files]
    if any(number < 0 for number in numbers) or len(set(numbers)) != len(numbers):
        return "file numbers must be distinct and 0 or more", 0, len(rows)
    ledger = read_ledger(workspace, root_name)
    if ledger is None:
        return "the folder's file numbers are not recorded", 0, len(rows)
    if any(ledger["files"].get(str(row.i)) != row.path for row in page.files):
        return "a file's number differs from the folder's record", 0, len(rows)
    return None, len(expected), len(rows)


def verify_output(input_value, output_value, workspace):
    problem, shown, total = page_problem(input_value.root, input_value.offset, input_value.limit, output_value, workspace)
    if problem:
        return result(False, problem)
    return result(True, f"{shown} of {total} files, as on disk", files=shown, total=total)
