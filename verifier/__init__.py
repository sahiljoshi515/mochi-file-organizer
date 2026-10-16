"""The deterministic verifier: each tool's checks live in its own module, on contract instances; the
rules themselves (naming, sniff, meta, formats, inflate, walk, plan, layout) are byte-identical copies
of src/plugin's, so the tools and the checks decide from one piece of code."""

from contract import Task, Tool

from . import apply, pin, survey, task

TOOLS = {
    Tool.PIN_LAYOUT: pin,
    Tool.SURVEY: survey,
    Tool.APPLY: apply,
}
# task -> its outcome check, verify_task(arguments, output, reference, workspace)
TASKS = {Task.ORGANIZE_FOLDER: task.verify_task}


def verify_input(tool, value):
    return TOOLS[Tool(tool)].verify_input(value)


def verify_output(tool, input_value, output_value, workspace):
    return TOOLS[Tool(tool)].verify_output(input_value, output_value, workspace)


def verify_task(task, arguments, output, reference, workspace):
    return TASKS[Task(task)](arguments, output, reference, workspace)
