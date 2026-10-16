"""Each tool's and task's typed input and output (see nanoagent.plugin.contract): declarations only."""

from dataclasses import dataclass
from enum import Enum
from typing import Annotated

from slimconfig import Output


class Tool(Enum):
    PIN_LAYOUT = "pin_layout"
    SURVEY = "survey"
    APPLY = "apply"


class Task(Enum):
    ORGANIZE_FOLDER = "organize-folder"


class Drop(Enum):
    JUNK = "junk"
    EMPTY = "empty"
    COPY = "copy"


class Action(Enum):
    STAY = "stay"
    MOVE = "move"
    DELETE = "delete"


class Reason(Enum):
    IN_PLACE = "in-place"
    RULES = "rules"
    JUNK = "junk"
    EMPTY = "empty"
    COPY = "copy"


class DateSource(Enum):
    EXIF = "exif"
    PNG_TEXT = "png-text"
    PDF = "pdf"
    OFFICE = "office"
    ODF = "odf"
    MVHD = "mvhd"
    FRONT_MATTER = "front-matter"
    NAME = "name"
    NONE = "none"


FOLDER = (
    "The folder to organize, relative to your File Organizer agent folder (home/<you>/agent/file-organizer/),"
    " e.g. Downloads; . for the whole agent folder"
)
RELATIVE = "A path relative to the folder"


@dataclass
class OrganizeInput(Output):
    folder: Annotated[str, FOLDER]


@dataclass
class OrganizeOutput(Output):
    folder: Annotated[str, "The folder organized, as the task named it"]
    files: Annotated[int, "How many files took part (hidden ones never do)"]
    moved: Annotated[int, "How many files this run moved to their place"]
    deleted: Annotated[int, "How many duplicates, junk and empty files this run deleted"]
    stayed: Annotated[int, "How many files were already in place"]
    left: Annotated[int, "How many of this run's actions were not done"]
    remaining: Annotated[int, "How many actions wait for the next run (one run does at most 60)"]


@dataclass
class Row(Output):
    i: Annotated[int, "The file's number in the rules' order; apply names files by it"]
    path: Annotated[str, RELATIVE]
    h: Annotated[str, "The start of the file's sha256: rows with the same h hold the same bytes"]
    base: Annotated[str | None, "Where the rules file it (relative to the folder), before any _<n> suffix; null for a row with drop"]
    drop: Annotated[Drop | None, "junk, empty, or copy (the same bytes as a file already in place): delete it; null otherwise"]


@dataclass
class SurveyOutput(Output):
    folder: Annotated[str, "The folder"]
    rows: Annotated[list[Row], "This run's files to act on, at most 60, in order of i"]
    note: Annotated[str, "What the folder holds and what this run does, in a sentence"]
    summary: Annotated[OrganizeOutput, "The run so far: submit the last one you get, as it is"]


@dataclass
class Move(Output):
    i: Annotated[int, "The row's i"]
    n: Annotated[int, "1 + how many earlier rows you are moving with the same base"]


@dataclass
class ApplyInput(Output):
    folder: Annotated[str, FOLDER]
    moves: Annotated[list[Move], "Rows to move to their base (with a _<n> suffix from n 2 on)"]
    deletes: Annotated[list[int], "The i of every row to delete"]


@dataclass
class ApplyOutput(Output):
    applied: Annotated[int, "How many of this call's moves and deletes were done"]
    errors: Annotated[list[str], "Each move or delete that was refused, with why; the others were done"]
    summary: Annotated[OrganizeOutput, "The run so far: submit the last one you get, as it is"]


@dataclass
class PinnedFile(Output):
    i: Annotated[int, "The file's place in the rules' order"]
    path: Annotated[str, RELATIVE]
    size: Annotated[int, "Bytes"]
    sha256: Annotated[str, "The file's SHA-256 hex digest"]
    type: Annotated[str, "The sniffed type: the folder below the group"]
    group: Annotated[str, "documents, images, audio, video, spreadsheets, presentations, data, code, archives or other"]
    ext: Annotated[str, "The extension the rules give it"]
    date_source: Annotated[DateSource, "Where its date came from"]
    date_raw: Annotated[str | None, "The embedded date value as stored (at most 64 characters), or the name it came from; null when undated"]
    date: Annotated[str | None, "YYYY-MM-DD, or null when undated"]
    slug: Annotated[str, "Its slug"]
    base: Annotated[str | None, "Its base path; null for junk and empty files"]
    junk: Annotated[bool, "Whether its name is junk"]
    conforming: Annotated[bool, "Whether it already sits at its base path or a _<n> form of it"]
    action: Annotated[Action, "What the rules do with it"]
    reason: Annotated[Reason, "Why"]
    copy_of: Annotated[int | None, "For a copy: the i of the file kept"]
    target: Annotated[str | None, "Where it ends: its own path when it stays, the move's destination, null when deleted"]
    quota: Annotated[bool, "Whether this run acts on it (the first 60 actions)"]


@dataclass
class KeptEntry(Output):
    path: Annotated[str, "A path relative to your agent folder"]
    folder: Annotated[bool, "Whether it is a folder"]
    size: Annotated[int, "Bytes; 0 for a folder"]
    sha256: Annotated[str | None, "The file's SHA-256 hex digest; null for a folder"]


@dataclass
class PinOutput(Output):
    folder: Annotated[str, "The folder"]
    files: Annotated[list[PinnedFile], "Every file that takes part, in order"]
    taken: Annotated[list[str], "Every path under organized/ that the run starts with (empty folders aside)"]
    kept: Annotated[
        list[KeptEntry],
        "Everything the run leaves exactly as it was: the hidden files and folders in the folder, and every file and"
        " folder in the agent folder outside it (the plugin's run state aside), by path",
    ]
    pending: Annotated[int, "How many actions the folder needs in all"]
    quota: Annotated[int, "How many of them this run does"]
    entries_after: Annotated[int, "How many files and folders the agent folder holds after this run"]


TOOLS = {
    Tool.PIN_LAYOUT: (OrganizeInput, PinOutput),
    Tool.SURVEY: (OrganizeInput, SurveyOutput),
    Tool.APPLY: (ApplyInput, ApplyOutput),
}
TASKS = {Task.ORGANIZE_FOLDER: (OrganizeInput, OrganizeOutput)}
