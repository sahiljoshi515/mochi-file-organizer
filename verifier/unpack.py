"""unpack_inbox: the messy folder exists at the task root; a fresh or untouched one holds exactly the
size's files under inbox/ and nothing elsewhere, and a worked-on one is reported as it is."""

from .checks import result, root_problem, seed_problem, task_root
from .inventory import MAX_LIMIT, page_problem
from .rules import COUNTS, INBOX, files_under, root_name
from .rules_text import HEADINGS


def verify_input(value):
    problem = seed_problem(value)
    if problem:
        return result(False, problem)
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    expected = root_name(input_value.seed, input_value.size.value)
    if output_value.root != expected or root_problem(output_value.root):
        return result(False, f"the folder must be at {expected}")
    missing = [heading for heading in HEADINGS if heading not in output_value.rules]
    if missing:
        return result(False, f"the rules it returns lack the section(s) {', '.join(missing)}")
    root = task_root(workspace, input_value)
    if not root.is_dir():
        return result(False, f"{expected} was not made")
    problem, _shown, _total = page_problem(expected, 0, MAX_LIMIT, output_value.inventory, workspace)
    if problem:
        return result(False, f"the inventory page it returns is wrong: {problem}")
    inbox = root / INBOX
    in_inbox = len(files_under(inbox)) if inbox.is_dir() else 0
    if output_value.files != in_inbox:
        return result(False, f"{INBOX}/ holds {in_inbox} files, not {output_value.files}")
    if output_value.complete:
        return result(True, f"the folder was already worked on; {in_inbox} files remain in {INBOX}/", files=in_inbox, complete=True)
    wanted = COUNTS[input_value.size.value]
    if in_inbox != wanted:
        return result(False, f"a fresh {input_value.size.value} folder holds {wanted} files under {INBOX}/, not {in_inbox}")
    elsewhere = len(files_under(root)) - in_inbox
    if elsewhere:
        return result(False, f"{elsewhere} file(s) lie outside {INBOX}/ although the folder is reported untouched")
    return result(True, f"the messy folder holds {in_inbox} files", files=in_inbox, dirs=output_value.dirs, complete=False)
