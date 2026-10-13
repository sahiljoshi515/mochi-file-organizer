"""read_rules: the rules document, which must at least hold every section of the rules."""

from .checks import result

HEADINGS = ("## 1. Delete", "## 2. Category and extension", "## 3. Date", "## 4. Slug", "## 5. Collisions")


def verify_input(value):
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    missing = [heading for heading in HEADINGS if heading not in output_value.rules]
    if missing:
        return result(False, f"the rules lack the section(s) {', '.join(missing)}")
    return result(True, "the rules are complete", characters=len(output_value.rules))
