"""pin_inventory (the organize reference) and the organize task's outcome check."""

from .checks import is_sha256, result, root_problem, seed_problem, task_root
from .rules import COUNTS, INBOX, ORGANIZED, files_under, inventory_rows, plan, root_name, sha256_of, target_problem

# How many entries each list of problems shows; the counts are always whole.
SHOWN = 100


def verify_input(value):
    problem = seed_problem(value)
    if problem:
        return result(False, problem)
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    """The pin must be exactly the rules applied to the folder the tool made in this workspace."""
    expected_root = root_name(input_value.seed, input_value.size.value)
    if output_value.seed != input_value.seed or output_value.size != input_value.size or output_value.root != expected_root:
        return result(False, "the pin is for another folder")
    if root_problem(output_value.root):
        return result(False, "the pin's root is not a task root")
    root = task_root(workspace, input_value)
    if not (root / INBOX).is_dir():
        return result(False, f"{expected_root}/{INBOX} was not made")
    rows = inventory_rows(root)
    wanted = COUNTS[input_value.size.value]
    if len(rows) != wanted or output_value.files != wanted:
        return result(False, f"a {input_value.size.value} folder holds {wanted} files, not {len(rows)} (pinned {output_value.files})")
    pinned = [(row.sha256, row.path) for row in output_value.expected]
    if any(not is_sha256(digest) or target_problem(path) for digest, path in pinned):
        return result(False, "a pinned entry is not a sha256 at a path the rules could give")
    if len({digest for digest, _path in pinned}) != len(pinned) or len({path for _digest, path in pinned}) != len(pinned):
        return result(False, "the pin lists a hash or a path twice")
    planned = plan(rows)
    if pinned != list(planned.expected):
        return result(False, "the pinned layout differs from the rules applied to the folder")
    counts = (output_value.unique, output_value.duplicates, output_value.removed)
    if counts != (planned.unique, planned.duplicates, planned.removed):
        return result(False, "the pinned counts differ from the rules applied to the folder")
    return result(
        True,
        f"{planned.unique} files pinned",
        files=wanted,
        unique=planned.unique,
        duplicates=planned.duplicates,
        removed=planned.removed,
    )


def _label(count, one, many=None):
    return f"{count} {one if count == 1 else (many or one + 's')}"


def verify_task(arguments, reference, workspace):
    """Approve the folder only when every pinned file sits at its pinned path, once, and nothing else
    is left anywhere; score it by the share of pinned files in place."""
    summary = {
        "files": reference.files,
        "unique": reference.unique,
        "duplicates": reference.duplicates,
        "removed": reference.removed,
    }
    if reference.seed != arguments.seed or reference.size != arguments.size:
        return result(False, "the pinned inventory is for another folder", score=0.0, **summary)
    root = task_root(workspace, arguments)
    if not root.is_dir():
        return result(False, "the folder was never unpacked", score=0.0, **summary)

    expected = {row.sha256: row.path for row in reference.expected}
    organized = {}
    leftovers = []
    for path in files_under(root):
        relative = path.relative_to(root).as_posix()
        if relative.startswith(ORGANIZED + "/"):
            organized[relative] = sha256_of(path)
        else:
            leftovers.append(relative)
    leftovers += sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_symlink())
    by_hash = {}
    for relative, digest in sorted(organized.items()):
        by_hash.setdefault(digest, []).append(relative)

    placed = 0
    missing, misplaced, duplicates_kept = [], [], []
    for digest, wanted in sorted(expected.items(), key=lambda pair: pair[1]):
        paths = by_hash.get(digest, [])
        if not paths:
            missing.append({"sha256": digest, "expected": wanted})
        elif wanted in paths:
            placed += 1
            if len(paths) > 1:
                duplicates_kept.append({"sha256": digest, "expected": wanted, "extra": [path for path in paths if path != wanted]})
        else:
            misplaced.append({"sha256": digest, "expected": wanted, "actual": paths})
    extra = sorted(path for digest, paths in by_hash.items() if digest not in expected for path in paths)
    bad_names = [{"path": path, "problem": target_problem(path)} for path in sorted(organized) if target_problem(path)]

    unique = len(expected)
    score = placed / unique if unique else float(not organized and not leftovers)
    problems = []
    if missing:
        problems.append(f"{_label(len(missing), 'file')} missing")
    if misplaced:
        problems.append(f"{_label(len(misplaced), 'file')} misplaced")
    if duplicates_kept:
        problems.append(f"{_label(len(duplicates_kept), 'duplicate')} kept")
    if extra:
        problems.append(f"{_label(len(extra), 'other file')} in {ORGANIZED}/")
    if leftovers:
        problems.append(f"{_label(len(leftovers), 'file')} left outside {ORGANIZED}/")
    if bad_names:
        problems.append(f"{_label(len(bad_names), 'path')} not named by the rules")
    details = {
        **summary,
        "placed": placed,
        "missing": missing[:SHOWN],
        "misplaced": misplaced[:SHOWN],
        "duplicates_kept": duplicates_kept[:SHOWN],
        "extra": extra[:SHOWN],
        "leftovers": leftovers[:SHOWN],
        "bad_names": bad_names[:SHOWN],
    }
    if problems:
        return result(False, f"{placed} of {unique} files in place: " + ", ".join(problems), score=score, **details)
    return result(True, f"all {unique} files are in place and nothing else remains", score=score, **details)
