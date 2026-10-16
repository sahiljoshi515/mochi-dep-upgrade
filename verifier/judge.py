"""judge: once complete, its record (.judge/judgement.json) exists and agrees with what it returned;
an unfinished judge records nothing and says what is next."""

import json

from . import catalog
from .checks import project_root, result


def verify_input(value):
    try:
        catalog.entry(value.instance.value)
    except ValueError as error:
        return result(False, str(error))
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    if not output_value.complete:
        if output_value.recorded or not output_value.next.strip():
            return result(False, "an unfinished judge records nothing and says what to do next")
        return result(True, "judging continues", next=output_value.next)
    if not output_value.recorded or output_value.next.strip():
        return result(False, "a finished judge records the judgement and has nothing next")
    path = project_root(workspace, input_value.instance.value) / ".judge" / "judgement.json"
    if not path.is_file():
        return result(False, "no judgement in the workspace")
    try:
        judgement = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError):
        return result(False, "the judgement is not readable JSON")
    if judgement.get("instance") != input_value.instance.value or judgement.get("complete") is not True:
        return result(False, "the judgement is for another instance or not complete")
    recorded = sorted(item.get("path") for item in judgement.get("changed_files", []) if isinstance(item, dict))
    if recorded != sorted(output_value.changed_files):
        return result(False, "the reported changed files differ from the judgement")
    if (judgement.get("public") or {}).get("passed", 0) != output_value.public_passed:
        return result(False, "the reported public tests differ from the judgement")
    return result(True, "judgement is recorded", changed_files=len(recorded))
