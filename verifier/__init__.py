"""The deterministic verifier: each tool's checks live in its own module, on contract instances."""

from contract import Task, Tool

from . import inventory, pin, plan, rules_text, tree, unpack

TOOLS = {
    Tool.PIN_INVENTORY: pin,
    Tool.UNPACK_INBOX: unpack,
    Tool.READ_RULES: rules_text,
    Tool.INVENTORY: inventory,
    Tool.APPLY_PLAN: plan,
    Tool.LIST_TREE: tree,
}
# task -> its outcome check, verify_task(arguments, reference, workspace)
TASKS = {Task.ORGANIZE: pin.verify_task}


def verify_input(tool, value):
    return TOOLS[Tool(tool)].verify_input(value)


def verify_output(tool, input_value, output_value, workspace):
    return TOOLS[Tool(tool)].verify_output(input_value, output_value, workspace)


def verify_task(task, arguments, reference, workspace):
    return TASKS[Task(task)](arguments, reference, workspace)
