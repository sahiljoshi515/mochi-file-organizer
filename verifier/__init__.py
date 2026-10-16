"""The deterministic verifier: each tool's checks live in its own module, on contract instances; the
rules themselves (naming, sniff, meta, formats, inflate, walk, plan, layout) are byte-identical copies
of src/plugin's, so the tools and the checks decide from one piece of code."""

from contract import Task, Tool

from . import apply, pin, survey, task
from .checks import result

TOOLS = {
    Tool.PIN_LAYOUT: pin,
    Tool.SURVEY: survey,
    Tool.APPLY: apply,
}
# task -> its outcome check, verify_task(arguments, output, reference, workspace)
TASKS = {Task.ORGANIZE_FOLDER: task.verify_task}


def unreadable(error):
    """A verdict for a file system error no check foresaw: never raise, say what could not be read."""
    name = str(error.filename).rpartition("/")[2] if error.filename else "an entry"
    return result(False, f"The agent folder could not be read ({name}: {error.strerror or 'an error'}); fix it and ask again.", score=0.0)


def verify_input(tool, value):
    return TOOLS[Tool(tool)].verify_input(value)


def verify_output(tool, input_value, output_value, workspace):
    try:
        return TOOLS[Tool(tool)].verify_output(input_value, output_value, workspace)
    except OSError as error:
        return unreadable(error)


def verify_task(task, arguments, output, reference, workspace):
    try:
        return TASKS[Task(task)](arguments, output, reference, workspace)
    except OSError as error:
        return unreadable(error)
