"""The tools: pin the answer key (pin_layout), list this run's files to act on (survey), and move or
delete them by number (apply), in the member's own folder.

A run is one plugin process. Its first survey takes the snapshot and the plan and fixes the run's
quota (the first 60 actions in the rules' order); later surveys answer with the same rows. apply acts
only on those rows, checks each file's bytes before touching it, moves a file only to the n-th free
name of its base, and never deletes the last copy of anything. The run's state is also written to
.file-organizer/state.json in the agent folder, so the verifier can check every call.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from contract import (
    Action,
    ApplyInput,
    ApplyOutput,
    DateSource,
    Drop,
    OrganizeInput,
    OrganizeOutput,
    PinnedFile,
    PinOutput,
    Reason,
    Row,
    SurveyOutput,
)
from plugin import plan, walk
from plugin.layout import STATE_DIR, Layout, label, look, resolve
from plugin.naming import path_key

STATE_FILE = "state.json"
ITEM_LIMIT = 60
TOKEN = uuid.uuid4().hex  # this process, i.e. this run


@dataclass
class Run:
    snapshot: Layout
    rows: dict[int, plan.Step]
    taken_keys: set[str]
    location: dict[int, str]  # where each file is now (deleted files leave)
    occupied: set[str]  # keys of every path a file of the run sits at now
    applied: list[dict] = field(default_factory=list)
    calls: int = 0  # apply calls so far; each log entry names the call that made it


RUN: Run | None = None


# ----- The folder -----


def take_snapshot(workspace: Path, folder: str) -> Layout:
    """The folder under the rules, or ValueError saying what keeps the rules from it."""
    found = look(workspace, folder)
    if found.refused:
        raise ValueError(found.refused)
    return found


def folder_root(workspace: Path, folder: str) -> Path:
    root, problem = resolve(workspace, folder)
    if root is None:
        raise ValueError(problem)
    return root


# ----- pin_layout -----


def pinned(fact: walk.Facts, step: plan.Step) -> PinnedFile:
    return PinnedFile(
        i=step.i,
        path=fact.path,
        size=fact.size,
        sha256=fact.sha256,
        type=fact.type,
        group=fact.group,
        ext=fact.ext,
        date_source=DateSource(fact.date_source),
        date_raw=fact.date_raw,
        date=fact.date,
        slug=fact.slug,
        base=fact.base,
        junk=fact.junk,
        conforming=fact.conforming,
        action=Action(step.action),
        reason=Reason(step.reason),
        copy_of=step.copy_of,
        target=step.target,
        quota=step.quota,
    )


def pin_layout(given: OrganizeInput, workspace: Path) -> PinOutput:
    """The answer key: every file's facts and the rules' step for it, from this (scratch) copy of the agent folder."""
    snap = take_snapshot(workspace, given.folder)
    tally = plan.counts(snap.steps)
    return PinOutput(
        folder=given.folder,
        files=[pinned(fact, step) for fact, step in zip(snap.facts, snap.steps, strict=True)],
        taken=snap.taken,
        pending=tally["pending"],
        quota=tally["quota"],
        entries_after=snap.entries_after,
    )


# ----- survey -----


def drop_of(run: Run, step: plan.Step) -> Drop | None:
    if step.reason in (plan.JUNK, plan.EMPTY):
        return Drop(step.reason)
    if step.reason == plan.COPY and step.copy_of not in run.rows:
        return Drop.COPY  # a copy of a file already in place, which the rows do not show
    return None


def summary(run: Run) -> OrganizeOutput:
    tally = plan.counts(run.snapshot.steps)
    moved = sum(entry["kind"] == "move" for entry in run.applied)
    deleted = sum(entry["kind"] == "delete" for entry in run.applied)
    return OrganizeOutput(
        folder=run.snapshot.folder,
        files=tally["files"],
        moved=moved,
        deleted=deleted,
        stayed=tally["stayed"],
        left=tally["quota"] - moved - deleted,
        remaining=tally["remaining"],
    )


def rows_of(run: Run) -> list[Row]:
    snap = run.snapshot
    rows = []
    for i, step in sorted(run.rows.items()):
        drop = drop_of(run, step)
        rows.append(Row(i=i, path=step.path, h=step.sha256[: snap.hash_length], base=None if drop else snap.facts[i].base, drop=drop))
    return rows


def write_state(workspace: Path, run: Run) -> None:
    snap = run.snapshot
    state = {
        "version": 1,
        "token": TOKEN,
        "folder": snap.folder,
        "hash_length": snap.hash_length,
        "taken": snap.taken,
        "rows": [
            {
                "i": i,
                "path": step.path,
                "sha256": step.sha256,
                "base": None if drop_of(run, step) else snap.facts[i].base,
                "ext": snap.facts[i].ext,
                "drop": drop.value if (drop := drop_of(run, step)) else None,
            }
            for i, step in sorted(run.rows.items())
        ],
        "applied": run.applied,
        "calls": run.calls,
        "summary": json_summary(summary(run)),
    }
    folder = workspace / STATE_DIR
    folder.mkdir(exist_ok=True)
    temporary = folder / f"{STATE_FILE}.{TOKEN}.tmp"
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(temporary, folder / STATE_FILE)


def json_summary(value: OrganizeOutput) -> dict:
    return {key: getattr(value, key) for key in ("folder", "files", "moved", "deleted", "stayed", "left", "remaining")}


def survey(given: OrganizeInput, workspace: Path) -> SurveyOutput:
    """This run's rows: the first 60 actions the folder needs, with each file's hash prefix, base and drop."""
    global RUN
    if RUN is not None and RUN.snapshot.folder != given.folder:
        raise ValueError(f"this run organizes {label(RUN.snapshot.folder)}; ask for {label(given.folder)} in a new run")
    if RUN is None:
        snap = take_snapshot(workspace, given.folder)
        run = Run(
            snapshot=snap,
            rows={step.i: step for step in snap.steps if step.quota},
            taken_keys={path_key(path) for path in snap.taken},
            location={step.i: step.path for step in snap.steps},
            occupied={path_key(step.path) for step in snap.steps},
        )
        write_state(workspace, run)
        RUN = run
    run = RUN
    tally = plan.counts(run.snapshot.steps)
    if run.rows:
        first, last = min(run.rows), max(run.rows)
        acting = f"this run acts on the {len(run.rows)} rows below (i {first} to {last})"
    else:
        acting = "there is nothing to do: every file is already in place"
    waiting = f"; {tally['remaining']} more wait for a later run" if tally["remaining"] else ""
    note = f"{label(run.snapshot.folder)}: {tally['files']} files take part, {tally['stayed']} already in place; {acting}{waiting}."
    return SurveyOutput(folder=run.snapshot.folder, rows=rows_of(run), note=note, summary=summary(run))


# ----- apply -----


def present(root: Path, relative: str) -> bool:
    path = root / relative
    return path.is_file() and not path.is_symlink()


def other_copy(run: Run, root: Path, i: int) -> bool:
    """Whether a file other than `i` with the same bytes is still in the folder."""
    digest = run.snapshot.steps[i].sha256
    return any(
        other != i and step.sha256 == digest and other in run.location and present(root, run.location[other])
        for other, step in enumerate(run.snapshot.steps)
    )


def unchanged(root: Path, relative: str, digest: str) -> bool:
    return present(root, relative) and hashlib.sha256((root / relative).read_bytes()).hexdigest() == digest


def prune(root: Path) -> None:
    """Remove every empty folder inside `root` (never `root` itself, never inside a hidden folder)."""
    stack, folders = [root], []
    while stack:
        for entry in stack.pop().iterdir():
            if entry.is_dir() and not entry.is_symlink() and not entry.name.startswith("."):
                folders.append(entry)
                stack.append(entry)
    for folder in sorted(folders, key=lambda path: len(path.parts), reverse=True):
        try:
            folder.rmdir()
        except OSError:
            continue


def delete_one(run: Run, root: Path, i: int) -> str | None:
    step = run.rows.get(i)
    if step is None:
        return "not one of this run's rows"
    if any(entry["i"] == i for entry in run.applied):
        return "already done"
    relative = run.location[i]
    if not unchanged(root, relative, step.sha256):
        return "the file is gone or changed since survey"
    if drop_of(run, step) is None and not other_copy(run, root, i):
        return "it is the only copy of its bytes, so it is moved, not deleted"
    (root / relative).unlink()
    del run.location[i]
    run.occupied.discard(path_key(relative))
    run.applied.append({"i": i, "kind": "delete", "path": relative, "call": run.calls})
    return None


def move_one(run: Run, root: Path, i: int, n: int) -> str | None:
    step = run.rows.get(i)
    if step is None:
        return "not one of this run's rows"
    if any(entry["i"] == i for entry in run.applied):
        return "already done"
    if drop_of(run, step) is not None:
        return f"a row with drop ({drop_of(run, step).value}) is deleted, never moved"
    if not 1 <= n <= plan.MAX_NUMBER:
        return f"n must be 1 to {plan.MAX_NUMBER}"
    fact = run.snapshot.facts[i]
    destination = plan.nth_free(fact.base, fact.ext, run.taken_keys, n)
    if destination is None:
        return f"no free name for n {n}"
    if path_key(destination) in run.occupied:
        return f"{destination} is already taken in this run: check n"
    relative = run.location[i]
    if not unchanged(root, relative, step.sha256):
        return "the file is gone or changed since survey"
    target = root / destination
    for parent in reversed(target.parents):
        if parent == root or root.is_relative_to(parent):
            continue
        if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
            return f"{parent.relative_to(root).as_posix()} is not a folder"
    if target.exists() or target.is_symlink():
        return f"{destination} exists"
    target.parent.mkdir(parents=True, exist_ok=True)
    (root / relative).rename(target)
    run.location[i] = destination
    run.occupied.discard(path_key(relative))
    run.occupied.add(path_key(destination))
    run.applied.append({"i": i, "kind": "move", "n": n, "from": relative, "to": destination, "call": run.calls})
    return None


def apply(given: ApplyInput, workspace: Path) -> ApplyOutput:
    """Delete, then move, this run's rows by number; a refused item is reported and the rest are done."""
    run = RUN
    if run is None or run.snapshot.folder != given.folder:
        raise ValueError(f"call survey with folder {given.folder} first: apply acts only on the rows a survey of this run listed")
    if len(given.moves) + len(given.deletes) > ITEM_LIMIT:
        raise ValueError(f"at most {ITEM_LIMIT} moves and deletes per call")
    root = folder_root(workspace, given.folder)
    run.calls += 1
    errors: list[str] = []
    applied = 0
    for i in given.deletes:
        why = delete_one(run, root, i)
        if why:
            errors.append(f"delete {i}: {why}")
        else:
            applied += 1
    for move in given.moves:
        why = move_one(run, root, move.i, move.n)
        if why:
            errors.append(f"move {move.i}: {why}")
        else:
            applied += 1
    prune(root)
    write_state(workspace, run)
    return ApplyOutput(applied=applied, errors=errors, summary=summary(run))
