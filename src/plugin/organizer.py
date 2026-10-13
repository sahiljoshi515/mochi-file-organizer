"""The tools: make the messy folder, read the rules, inventory it, apply moves and deletes by file
number, list it, and pin the answer key.

Every path a tool takes or gives is relative to the task root. Every file carries a number, `i`,
given once from the first full listing of the root and kept for the whole task: a file keeps its
number when it moves, and a deleted file's number is never given again. The numbers live in the
plugin process and beside the root (file-organizer/<seed>-<size>.ids.json), so they survive a new
process and the verifier can check them.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from contract import (
    ExpectedFile,
    InventoryFile,
    InventoryInput,
    InventoryOutput,
    OrganizeInput,
    PinOutput,
    PlanInput,
    PlanOutput,
    RulesInput,
    RulesOutput,
    TreeInput,
    TreeOutput,
    UnpackOutput,
)
from plugin import generate, rules
from plugin.common import confine

RULES_PATH = Path(__file__).with_name("RULES.md")
PAGE_LIMIT = 100
MOVE_LIMIT = 80
DELETE_LIMIT = 80
TREE_LIMIT = 200
ERROR_LIMIT = 50
LEDGER_SUFFIX = ".ids.json"


@dataclass
class Ledger:
    """Each file's number for one task root."""

    files: dict[int, str] = field(default_factory=dict)  # number -> the file's current path
    deleted: dict[int, str] = field(default_factory=dict)  # number -> the path the file had


# The ledgers this process has loaded, by resolved root.
LEDGERS: dict[Path, Ledger] = {}


def task_root(workspace: Path, root: str) -> Path:
    """The existing task folder `root` names in the workspace."""
    if not rules.ROOT.fullmatch(root):
        raise ValueError("root must be file-organizer/<seed>-<size>, as unpack_inbox returns it")
    path = confine(workspace, root)
    if not path.is_dir():
        raise FileNotFoundError(f"{root} is not a folder in the workspace: call unpack_inbox first")
    return path


def ledger_file(workspace: Path, root_name: str) -> Path:
    return confine(workspace, root_name + LEDGER_SUFFIX)


def save_ledger(workspace: Path, root_name: str, ledger: Ledger) -> None:
    data = {
        "files": {str(number): path for number, path in sorted(ledger.files.items())},
        "deleted": {str(number): path for number, path in sorted(ledger.deleted.items())},
    }
    ledger_file(workspace, root_name).write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")


def load_ledger(workspace: Path, root_name: str, root: Path) -> Ledger:
    """The root's ledger, from this process or its file; any file it does not know yet gets the
    next number (the first listing numbers them all, in path order)."""
    ledger = LEDGERS.get(root)
    if ledger is None:
        record = ledger_file(workspace, root_name)
        if record.is_file():
            data = json.loads(record.read_text(encoding="utf-8"))
            ledger = Ledger(
                files={int(number): path for number, path in data["files"].items()},
                deleted={int(number): path for number, path in data["deleted"].items()},
            )
        else:
            ledger = Ledger()
        LEDGERS[root] = ledger
    known = set(ledger.files.values())
    following = max([*ledger.files, *ledger.deleted], default=-1) + 1
    for path in rules.files_under(root):
        relative = path.relative_to(root).as_posix()
        if relative not in known:
            ledger.files[following] = relative
            following += 1
    save_ledger(workspace, root_name, ledger)
    return ledger


def forget_ledger(workspace: Path, root_name: str, root: Path) -> None:
    LEDGERS.pop(root, None)
    record = ledger_file(workspace, root_name)
    if record.is_file():
        record.unlink()


def make_root(workspace: Path, given: OrganizeInput) -> tuple[str, Path, int, int]:
    """A fresh messy folder for the task input: its name, path and counts. The folder may exist
    only without files (an empty tree is replaced); a folder with files is never touched."""
    name = rules.root_name(given.seed, given.size.value)
    root = confine(workspace, name)
    try:
        if root.is_symlink():
            root.unlink()
        elif root.is_dir():
            if rules.files_under(root):
                raise ValueError(f"{name} already holds files: it is never made over")
            shutil.rmtree(root)
        elif root.exists():
            root.unlink()
        forget_ledger(workspace, name, root)
        files, dirs = generate.generate(root, given.seed, given.size.value)
    except OSError as error:
        raise RuntimeError(f"could not make {name}: {error.strerror or type(error).__name__}") from None
    return name, root, files, dirs


def folders_under(folder: Path) -> int:
    return sum(1 for path in folder.rglob("*") if path.is_dir() and not path.is_symlink()) if folder.is_dir() else 0


def untouched_note(files: int, dirs: int) -> str:
    return f"{files} files in {dirs} folders under {rules.INBOX}/, untouched; {rules.ORGANIZED}/ holds nothing"


def rules_text() -> str:
    return RULES_PATH.read_text(encoding="utf-8")


def unpack_inbox(given: OrganizeInput, workspace: Path) -> UnpackOutput:
    """The messy folder, made once, with the rules: an existing untouched folder gives the same
    answer again, and one already worked on is left exactly as it is (complete: true), never made
    over."""
    name = rules.root_name(given.seed, given.size.value)
    root = confine(workspace, name)
    text = rules_text()
    present = rules.files_under(root) if root.is_dir() and not root.is_symlink() else []
    if present:
        inbox = root / rules.INBOX
        in_inbox = [path for path in present if path.relative_to(root).parts[0] == rules.INBOX]
        dirs = folders_under(inbox)
        pristine = {(spec.path, hashlib.sha256(spec.data).hexdigest()) for spec in generate.build(given.seed, given.size.value)[0]}
        found = {(path.relative_to(root).as_posix(), rules.sha256_of(path)) for path in present}
        if found == pristine:
            return UnpackOutput(root=name, files=len(in_inbox), dirs=dirs, complete=False, note=untouched_note(len(in_inbox), dirs), rules=text)
        elsewhere = len(present) - len(in_inbox)
        note = (
            f"already unpacked and worked on: {len(in_inbox)} files still under {rules.INBOX}/ and {elsewhere} elsewhere in the"
            " folder; nothing was changed, carry on with inventory"
        )
        return UnpackOutput(root=name, files=len(in_inbox), dirs=dirs, complete=True, note=note, rules=text)
    name, root, files, dirs = make_root(workspace, given)
    (root / rules.ORGANIZED).mkdir(exist_ok=True)
    return UnpackOutput(root=name, files=files, dirs=dirs, complete=False, note=untouched_note(files, dirs), rules=text)


def pin_inventory(given: OrganizeInput, workspace: Path) -> PinOutput:
    """The rules applied to the messy folder, made in this (scratch) workspace: every kept file's
    hash and final path. It refuses a workspace that already holds the folder."""
    name, root, files, _dirs = make_root(workspace, given)
    planned = rules.plan(rules.inventory_rows(root))
    return PinOutput(
        seed=given.seed,
        size=given.size,
        root=name,
        files=files,
        unique=planned.unique,
        duplicates=planned.duplicates,
        removed=planned.removed,
        expected=[ExpectedFile(sha256=digest, path=path) for digest, path in planned.expected],
    )


def read_rules(given: RulesInput, workspace: Path) -> RulesOutput:
    return RulesOutput(rules=rules_text())


def inventory(given: InventoryInput, workspace: Path) -> InventoryOutput:
    """One page of every file under the task root, sorted by path, each with its number."""
    if given.offset < 0:
        raise ValueError("offset must be 0 or more")
    if not 1 <= given.limit <= PAGE_LIMIT:
        raise ValueError(f"limit must be 1 to {PAGE_LIMIT}")
    root = task_root(workspace, given.root)
    ledger = load_ledger(workspace, given.root, root)
    numbers = {path: number for number, path in ledger.files.items()}
    rows = rules.inventory_rows(root)
    following = given.offset + given.limit
    return InventoryOutput(
        root=given.root,
        total=len(rows),
        next=following if following < len(rows) else None,
        files=[InventoryFile(i=numbers[row.path], **dataclasses.asdict(row)) for row in rows[given.offset : following]],
    )


def _why(error: Exception) -> str:
    if isinstance(error, OSError) and error.strerror:
        return error.strerror.lower()
    return str(error)


def located(ledger: Ledger, number: int) -> str:
    """The current path of file `number`, or why there is none."""
    if number in ledger.files:
        return ledger.files[number]
    if number in ledger.deleted:
        raise ValueError("already deleted")
    raise ValueError("unknown number: not in the inventory")


def prune(folder: Path) -> int:
    """Remove every empty folder below `folder` (never `folder` itself); how many went."""
    removed = 0
    below = [path for path in folder.rglob("*") if path.is_dir() and not path.is_symlink()]
    for path in sorted(below, key=lambda path: len(path.parts), reverse=True):
        try:
            path.rmdir()
        except OSError:
            continue
        removed += 1
    return removed


def apply_plan(given: PlanInput, workspace: Path) -> PlanOutput:
    """Move then delete files by number inside the task root; an item that fails is reported, the
    rest go on. A moved file keeps its number at its new path; a deleted number is spent."""
    if len(given.moves) > MOVE_LIMIT or len(given.deletes) > DELETE_LIMIT:
        raise ValueError(f"at most {MOVE_LIMIT} moves and {DELETE_LIMIT} deletes per call: apply the plan in batches")
    root = task_root(workspace, given.root)
    ledger = load_ledger(workspace, given.root, root)
    errors: list[str] = []
    moved = deleted = 0

    def report(label: str, why: str) -> None:
        if len(errors) < ERROR_LIMIT:
            errors.append(f"{label}: {why}")
        elif len(errors) == ERROR_LIMIT:
            errors.append("more errors not shown")

    for move in given.moves:
        label = f"move {move.i} -> {move.dst}"
        try:
            current = located(ledger, move.i)
            if not move.dst.startswith(rules.ORGANIZED + "/") or move.dst.endswith("/"):
                raise ValueError(f"the destination must be a file path under {rules.ORGANIZED}/")
            source = confine(root, current)
            destination = confine(root, move.dst)
            if source.is_symlink() or not source.is_file():
                raise ValueError("not a file")
            if destination.exists() or destination.is_symlink():
                raise ValueError("the destination exists")
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.rename(destination)
        except (OSError, ValueError) as error:
            report(label, _why(error))
            continue
        ledger.files[move.i] = move.dst
        moved += 1
    for number in given.deletes:
        label = f"delete {number}"
        try:
            current = located(ledger, number)
            path = confine(root, current)
            if path.is_symlink() or not path.is_file():
                raise ValueError("not a file")
            path.unlink()
        except (OSError, ValueError) as error:
            report(label, _why(error))
            continue
        del ledger.files[number]
        ledger.deleted[number] = current
        deleted += 1
    save_ledger(workspace, given.root, ledger)
    removed_dirs = sum(prune(root / name) for name in (rules.INBOX, rules.ORGANIZED) if (root / name).is_dir())
    return PlanOutput(moved=moved, deleted=deleted, removed_dirs=removed_dirs, errors=errors)


def list_tree(given: TreeInput, workspace: Path) -> TreeOutput:
    """The folder's files and sub-folders, as sorted paths relative to root."""
    if not 1 <= given.max_entries <= TREE_LIMIT:
        raise ValueError(f"max_entries must be 1 to {TREE_LIMIT}")
    root = task_root(workspace, given.root)
    entries: list[str] = []
    files = dirs = 0
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            continue
        if path.is_dir():
            dirs += 1
            entries.append(relative + "/")
        elif path.is_file():
            files += 1
            entries.append(relative)
    entries.sort()
    return TreeOutput(
        root=given.root,
        files=files,
        dirs=dirs,
        entries=entries[: given.max_entries],
        truncated=len(entries) > given.max_entries,
    )
