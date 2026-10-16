"""pin_layout, the organize-folder task's answer key: the folder is one the task may name, and the pin is
exactly the rules applied to the agent folder copy it was taken from."""

from pathlib import Path

from .checks import result
from .layout import folder_problem, look
from .naming import base_path, conforms
from .plan import ordered, plan
from .walk import Facts

FACT_FIELDS = ("path", "size", "sha256", "junk", "group", "type", "ext", "date_source", "date_raw", "date", "slug", "base", "conforming")
STEP_FIELDS = ("action", "reason", "copy_of", "target", "quota")


def verify_input(value):
    problem = folder_problem(value.folder)
    if problem:
        return result(False, problem)
    return result(True, "input is valid")


def pinned_row(file):
    """A PinnedFile as plain values, in FACT_FIELDS then STEP_FIELDS order."""
    return (
        file.path, file.size, file.sha256, file.junk, file.group, file.type, file.ext, file.date_source.value,
        file.date_raw, file.date, file.slug, file.base, file.conforming,
        file.action.value, file.reason.value, file.copy_of, file.target, file.quota,
    )  # fmt: skip


def derived_row(fact, step):
    return (
        fact.path, fact.size, fact.sha256, fact.junk, fact.group, fact.type, fact.ext, fact.date_source,
        fact.date_raw, fact.date, fact.slug, fact.base, fact.conforming,
        step.action, step.reason, step.copy_of, step.target, step.quota,
    )  # fmt: skip


def first_difference(pinned, derived):
    """'file i: field pinned X, the rules give Y' for the first difference, or None."""
    if len(pinned) != len(derived):
        return f"the pin lists {len(pinned)} files, the rules see {len(derived)}"
    for index, (left, right) in enumerate(zip(pinned, derived, strict=True)):
        for name, one, other in zip(FACT_FIELDS + STEP_FIELDS, left, right, strict=True):
            if one != other:
                return f"file {index} ({right[0]}): {name} pinned {one!r}, the rules give {other!r}"
    return None


def verify_output(input_value, output_value, workspace):
    """Re-derive the whole answer key from the scratch copy the reference read, and require it exactly."""
    if output_value.folder != input_value.folder:
        return result(False, "the pin is for another folder")
    found = look(Path(workspace), input_value.folder)
    if found.refused:
        return result(False, f"the rules refuse this folder, yet a pin was made: {found.refused}")
    if [file.i for file in output_value.files] != list(range(len(output_value.files))):
        return result(False, "the pinned files are not numbered 0, 1, 2, … in order")
    problem = first_difference([pinned_row(file) for file in output_value.files], [derived_row(fact, step) for fact, step in zip(found.facts, found.steps, strict=True)])
    if problem:
        return result(False, f"the pin differs from the rules applied to the folder: {problem}")
    stays = sum(step.action == "stay" for step in found.steps)
    quota = sum(step.quota for step in found.steps)
    if output_value.taken != found.taken:
        return result(False, "the pinned taken paths differ from the folder's")
    if (output_value.pending, output_value.quota) != (len(found.steps) - stays, quota):
        return result(False, "the pinned counts differ from the rules applied to the folder")
    if output_value.entries_after != found.entries_after:
        return result(False, f"the pin projects {output_value.entries_after} entries after the run, the rules {found.entries_after}")
    return result(True, f"{len(found.steps)} files pinned: {stays} in place, {quota} actions this run", files=len(found.steps))


def rederive(reference):
    """Why the pinned plan is not the rules applied to the pinned facts, or None (the answer-key check)."""
    facts = []
    for file in reference.files:
        facts.append(
            Facts(
                path=file.path, size=file.size, sha256=file.sha256, junk=file.junk, group=file.group, type=file.type,
                ext=file.ext, date_source=file.date_source.value, date_raw=file.date_raw, date=file.date, slug=file.slug,
                base=file.base, conforming=file.conforming,
            )
        )
        if file.junk or file.size == 0:
            if file.base is not None:
                return f"{file.path} is junk or empty yet has a base path"
            continue
        if file.base != base_path(file.group, file.type, file.ext, file.date, file.slug):
            return f"{file.path}: its base path is not the one its facts give"
        if file.conforming != conforms(file.path, file.base, file.ext):
            return f"{file.path}: conforming is {file.conforming}, its path and base say otherwise"
    if [fact.path for fact in ordered(facts)] != [fact.path for fact in facts]:
        return "the pinned files are not in the rules' order"
    steps = plan(facts, reference.taken)
    for file, step in zip(reference.files, steps, strict=True):
        if (file.i, file.action.value, file.reason.value, file.copy_of, file.target, file.quota) != (
            step.i, step.action, step.reason, step.copy_of, step.target, step.quota,
        ):  # fmt: skip
            return f"{file.path}: the pinned step is not the rules' step"
    stays = sum(step.action == "stay" for step in steps)
    if (reference.pending, reference.quota) != (len(steps) - stays, sum(step.quota for step in steps)):
        return "the pinned counts are not the plan's"
    return None
