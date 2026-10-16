"""The organize-folder task's check: after the run, the folder is exactly what the rules make of this
run's quota, by hashes and paths, and the submitted summary says what happened.

From the pinned answer key it builds the expected end state E (path -> sha256: this run's moves at
their targets, its deletes gone, every other file where it was) and compares it with the folder as it
is, A, file by file. Every constraint is reported in details.constraints; the verdict is valid only
when all hold, and then, and only then, the score is 1.0.
"""

import hashlib
from pathlib import Path

from .checks import constraint, plural, result, shown
from .layout import SAVED_ENTRIES, label, resolve
from .pin import rederive
from .walk import count_below, describe, scan

CHECKS = (
    ("answer-key", "The answer key is the rules applied to the folder"),
    ("submitted-folder", "The submitted result names the folder the task asked for"),
    ("folder-present", "The folder is still in the agent folder"),
    ("every-file-kept", "Every content the folder must keep is still in it"),
    ("moved-to-rules-path", "Every file this run moves sits at the path the rules give it"),
    ("duplicates-and-junk-removed", "Every duplicate, junk and empty file this run deletes is gone"),
    ("others-untouched", "Every file this run does not act on is where it was, unchanged"),
    ("nothing-extra", "The folder holds no file the rules do not put there"),
    ("organized-by-rules", "Every file in place follows the rules for its own bytes"),
    ("summary-matches", "The submitted summary matches the folder"),
    ("saved-back", "The agent folder holds fewer than 5,000 entries, so RUSH Lab saves the result"),
)
TEXT = dict(CHECKS)
ROWS_SHOWN = 60


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def everything(workspace):
    """Files and folders in the whole agent folder, as RUSH Lab counts them before saving."""
    return count_below(Path(workspace))


def verify_task(arguments, output, reference, workspace):
    folder = arguments.folder
    named = label(folder)
    found = {}

    def put(key, ok, expected=None, actual=None, message=""):
        found[key] = constraint(key, TEXT[key], ok, expected, actual, message if ok is False else "")

    # 1-3: the answer key, the submission's folder, the folder itself.
    problem = "no answer key was pinned" if reference is None else None
    if problem is None and reference.folder != folder:
        problem = f"it is for {reference.folder}"
    if problem is None:
        problem = rederive(reference)
    put("answer-key", problem is None, "the rules applied to the pinned facts", problem or "as the rules give", f"The answer key does not match the folder (a plugin bug): {problem}.")
    put("submitted-folder", output.folder == folder, folder, output.folder, f"The result names {output.folder}, not {folder}.")
    root, missing = resolve(Path(workspace), folder)
    put("folder-present", root is not None, folder, "present" if root is not None else "gone", f"{named} is gone from your agent folder: {missing}")
    if problem is not None or root is None:
        for key, _text in CHECKS[3:]:
            put(key, None, actual="not checked: no answer key or no folder")
        return verdict(found, 0.0, folder, reference, [], 0)

    files = reference.files
    quota = [file for file in files if file.quota]
    expected = {}
    for file in files:
        if file.quota and file.action.value == "delete":
            continue
        expected[file.target if file.quota else file.path] = file.sha256
    scanned = scan(root)
    actual = {path: sha256(root / path) for path in scanned.files}
    held = {}
    for path, digest in sorted(actual.items()):
        held.setdefault(digest, []).append(path)

    # 4: every content the folder keeps.
    lost = sorted({digest for digest in expected.values() if digest not in held})
    lost_paths = sorted(path for path, digest in expected.items() if digest in lost)
    put("every-file-kept", not lost, f"{len(set(expected.values()))} contents", f"{len(lost)} gone", f"The contents of {plural(len(lost), 'file')} are gone: {', '.join(shown(lost_paths))}.")

    # 5: this run's moves at their targets.
    moves = [file for file in quota if file.action.value == "move"]
    misplaced = [file for file in moves if actual.get(file.target) != file.sha256]
    put(
        "moved-to-rules-path",
        not misplaced,
        f"{len(moves)} at their paths",
        f"{len(moves) - len(misplaced)} at their paths",
        f"{plural(len(misplaced), 'file')} not where the rules put them: "
        + ", ".join(shown(f"{file.path} belongs at {file.target}" + (f" (found at {held[file.sha256][0]})" if file.sha256 in held else "") for file in misplaced))
        + ".",
    )

    # 6: this run's deletes gone.
    deletes = [file for file in quota if file.action.value == "delete"]
    kept = [file for file in deletes if file.path in actual]
    put(
        "duplicates-and-junk-removed",
        not kept,
        f"{len(deletes)} gone",
        f"{len(deletes) - len(kept)} gone",
        f"{plural(len(kept), 'duplicate, junk or empty file', 'duplicate, junk or empty files')} still there: {', '.join(shown(file.path for file in kept))}.",
    )

    # 7: everything else where it was.
    others = [file for file in files if not file.quota or file.action.value == "stay"]
    moved_off = [file for file in others if actual.get(file.path) != file.sha256]
    put(
        "others-untouched",
        not moved_off,
        f"{len(others)} unchanged",
        f"{len(others) - len(moved_off)} unchanged",
        f"{plural(len(moved_off), 'file')} this run should not touch were changed or moved: {', '.join(shown(file.path for file in moved_off))}.",
    )

    # 8: nothing else in the folder.
    still_there = {file.path for file in kept}
    extra = sorted(path for path in actual if path not in expected and path not in still_there)
    extra += [line.rsplit(" is ", 1)[0] for line in scanned.problems]
    put("nothing-extra", not extra, "nothing else", f"{len(extra)} other", f"{plural(len(extra), 'file')} in the folder that should not be: {', '.join(shown(extra))}.")

    # 9: every file in place conforms, re-derived from its own bytes.
    placed = [file.target for file in files if file.action.value == "stay" or (file.quota and file.action.value == "move")]
    astray = []
    for path in placed:
        if actual.get(path) == expected.get(path) and not describe(path, (root / path).read_bytes()).conforming:
            astray.append(path)
    put(
        "organized-by-rules",
        not astray,
        "every file in place conforms",
        f"{len(astray)} do not",
        f"{plural(len(astray), 'file')} under organized/ do not follow the rules for their content: {', '.join(shown(astray))}.",
    )

    # 10: the submitted summary.
    pinned_paths = {file.path for file in files}
    new = [path for path in actual if path not in pinned_paths]
    gone = [file for file in quota if file.path not in actual]
    stays = sum(file.action.value == "stay" for file in files)
    want = {
        "folder": folder,
        "files": len(files),
        "moved": len(new),
        "deleted": len(gone) - len(new),
        "stayed": stays,
        "left": len(quota) - len(gone),
        "remaining": reference.pending - reference.quota,
    }
    got = {"folder": output.folder, "files": output.files, "moved": output.moved, "deleted": output.deleted, "stayed": output.stayed, "left": output.left, "remaining": output.remaining}
    wrong = [key for key in want if want[key] != got[key]]
    put(
        "summary-matches",
        not wrong,
        want,
        got,
        "The submitted summary says " + ", ".join(f"{key} {got[key]}" for key in wrong) + "; the folder shows " + ", ".join(f"{key} {want[key]}" for key in wrong) + ".",
    )

    # 11: RUSH Lab saves the result only below 5,000 entries.
    entries = everything(workspace)
    put("saved-back", entries < SAVED_ENTRIES, f"fewer than {SAVED_ENTRIES:,}", entries, f"The agent folder holds {entries:,} files and folders; RUSH Lab saves at most {SAVED_ENTRIES:,}, so nothing would be saved.")

    hits = len(moves) - len(misplaced) + len(deletes) - len(kept)
    paths = {file.target for file in misplaced} | {file.path for file in kept} | {file.path for file in moved_off} | set(extra) | set(astray)
    misses = len(paths) + sum(found[key]["ok"] is False for key in ("submitted-folder", "summary-matches", "saved-back"))
    score = 1.0 if hits + misses == 0 else hits / (hits + misses)
    rows = []
    for file in quota[:ROWS_SHOWN]:
        if file.action.value == "move":
            ok = actual.get(file.target) == file.sha256
            seen_at = None if ok else (held.get(file.sha256) or [None])[0]
        else:
            ok = file.path not in actual
            seen_at = None if ok else file.path
        rows.append({"i": file.i, "path": file.path, "action": file.action.value, "reason": file.reason.value, "target": file.target, "ok": ok, "found": seen_at})
    return verdict(found, score, folder, reference, rows, stays)


def verdict(found, score, folder, reference, rows, stays):
    entries = [found[key] for key, _text in CHECKS]
    failed = [entry for entry in entries if entry["ok"] is False]
    valid = not failed and all(entry["ok"] is True for entry in entries)
    named = label(folder)
    details = {
        "folder": folder,
        "files": len(reference.files) if reference is not None else 0,
        "quota": reference.quota if reference is not None else 0,
        "remaining": (reference.pending - reference.quota) if reference is not None else 0,
        "constraints": entries,
        "rows": rows,
    }
    if not valid:
        message = f"{len(failed)} of {len(entries)} checks failed. First: {failed[0]['message']} (score {score:.2f})" if failed else "The folder could not be checked."
        return result(False, message, score=min(score, 0.99) if score >= 1.0 else score, **details)
    files = reference.files
    moved = sum(file.quota and file.action.value == "move" for file in files)
    copies = sum(file.quota and file.reason.value == "copy" for file in files)
    junk = sum(file.quota and file.reason.value in ("junk", "empty") for file in files)
    remaining = reference.pending - reference.quota
    if reference.quota == 0:
        message = f"{named} is already organized: " + ("its one file is in place." if len(files) == 1 else f"all {len(files)} files are in place.")
    else:
        message = (
            f"Organized {named}: moved {moved}, deleted {copies + junk} ({plural(copies, 'duplicate copy', 'duplicate copies')},"
            f" {junk} junk or empty), {stays} already in place."
        )
    if remaining:
        message += f" {remaining} more: ask again to continue."
    return result(True, message[0].upper() + message[1:], score=1.0, **details)
