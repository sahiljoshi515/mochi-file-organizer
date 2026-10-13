"""Each tool's and task's typed input and output (see nanoagent.plugin.contract): declarations only."""

from dataclasses import dataclass
from enum import Enum
from typing import Annotated

from slimconfig import Output


class Tool(Enum):
    PIN_INVENTORY = "pin_inventory"
    UNPACK_INBOX = "unpack_inbox"
    READ_RULES = "read_rules"
    INVENTORY = "inventory"
    APPLY_PLAN = "apply_plan"
    LIST_TREE = "list_tree"


class Task(Enum):
    ORGANIZE = "organize"


class Size(Enum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


ROOT = "The task's folder, relative to the workspace: file-organizer/<seed>-<size>"
RELATIVE = "A file path relative to root, e.g. inbox/Photos/IMG_0042.JPG"
SHA256 = "The file's SHA-256 hex digest"


@dataclass
class OrganizeInput(Output):
    seed: Annotated[int, "Which messy folder to make: the same seed and size always give the same files"]
    size: Annotated[Size, "How many files: small 60, medium 150, large 300"]


@dataclass
class ExpectedFile(Output):
    sha256: Annotated[str, SHA256]
    path: Annotated[str, "Where the rules put it: organized/<category>/<YYYY>/<YYYY-MM-DD>_<slug>.<ext>"]


@dataclass
class PinOutput(Output):
    seed: int
    size: Size
    root: Annotated[str, ROOT]
    files: Annotated[int, "How many files the messy folder holds"]
    unique: Annotated[int, "How many files stay after deleting duplicates, junk and empty files"]
    duplicates: Annotated[int, "How many extra copies the rules delete"]
    removed: Annotated[int, "How many junk and empty files the rules delete"]
    expected: Annotated[list[ExpectedFile], "Every kept file's hash and final path, sorted by path"]


@dataclass
class UnpackOutput(Output):
    root: Annotated[str, ROOT]
    files: Annotated[int, "How many files inbox/ holds now"]
    dirs: Annotated[int, "How many folders inbox/ holds now"]
    complete: Annotated[bool, "True when the folder already existed and had been worked on, so it was left as it is; false when it was just made or is still untouched"]
    note: Annotated[str, "What was done, in a sentence"]
    rules: Annotated[str, "The organizing rules, Markdown (what read_rules returns)"]


@dataclass
class RulesInput(Output):
    pass


@dataclass
class RulesOutput(Output):
    rules: Annotated[str, "The organizing rules, Markdown"]


@dataclass
class InventoryInput(Output):
    root: Annotated[str, ROOT]
    offset: Annotated[int, "Skip this many files (they are sorted by path)"]
    limit: Annotated[int, "At most this many files, 1 to 100"]


@dataclass
class InventoryFile(Output):
    i: Annotated[int, "The file's number, the same for the whole task even after it moves: apply_plan names files by it"]
    path: Annotated[str, RELATIVE]
    size: Annotated[int, "Bytes"]
    sha256: Annotated[str, SHA256]
    type: Annotated[str, "The content type, sniffed: pdf png jpg docx zip svg html py json log md csv txt bin"]
    ext: Annotated[str, "The extension the name claims, as written; empty when it has none"]
    exif: Annotated[str | None, "JPEG EXIF DateTimeOriginal as stored (YYYY:MM:DD HH:MM:SS), or null"]
    png: Annotated[str | None, "PNG Creation Time text as stored, or null"]
    pdf: Annotated[str | None, "PDF /CreationDate as stored (D:YYYYMMDD...), or null"]
    md: Annotated[str | None, "Markdown front-matter date value as written, or null"]
    mtime_utc: Annotated[str, "Last modification time, YYYY-MM-DDTHH:MM:SSZ"]


@dataclass
class InventoryOutput(Output):
    root: Annotated[str, ROOT]
    total: Annotated[int, "How many files the folder holds in all"]
    next: Annotated[int | None, "The offset of the next page, or null when this was the last"]
    files: list[InventoryFile]


@dataclass
class Move(Output):
    i: Annotated[int, "The file's number from inventory"]
    dst: Annotated[str, "Its new path relative to root, under organized/; must not exist yet"]


@dataclass
class PlanInput(Output):
    root: Annotated[str, ROOT]
    moves: Annotated[list[Move], "Files to move, by number, in order; at most 80 per call"]
    deletes: Annotated[list[int], "Numbers of the files to delete; at most 80 per call"]


@dataclass
class PlanOutput(Output):
    moved: int
    deleted: int
    removed_dirs: Annotated[int, "Empty folders pruned under inbox/"]
    errors: Annotated[list[str], "Each move or delete that failed, with why; every other one was applied"]


@dataclass
class TreeInput(Output):
    root: Annotated[str, ROOT]
    max_entries: Annotated[int, "At most this many entries, 1 to 200"]


@dataclass
class TreeOutput(Output):
    root: Annotated[str, ROOT]
    files: Annotated[int, "How many files the folder holds"]
    dirs: Annotated[int, "How many folders"]
    entries: Annotated[list[str], "Paths relative to root, sorted; a folder ends with /"]
    truncated: Annotated[bool, "Whether entries stop before the end"]


TOOLS = {
    Tool.PIN_INVENTORY: (OrganizeInput, PinOutput),
    Tool.UNPACK_INBOX: (OrganizeInput, UnpackOutput),
    Tool.READ_RULES: (RulesInput, RulesOutput),
    Tool.INVENTORY: (InventoryInput, InventoryOutput),
    Tool.APPLY_PLAN: (PlanInput, PlanOutput),
    Tool.LIST_TREE: (TreeInput, TreeOutput),
}
TASKS = {Task.ORGANIZE: OrganizeInput}
