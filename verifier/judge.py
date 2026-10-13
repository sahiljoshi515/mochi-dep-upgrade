"""judge: the trusted tool's record, ``.judge/judgement.json``, must exist and match its output
once the judge reports ``complete``; an unfinished judge records nothing and says what is next."""

import json

from .checks import JUDGE_DIR, project_root, result

JUDGEMENT = "judgement.json"


def verify_input(value):
    return result(True, "input is valid")


def read_judgement(workspace, project):
    """The judgement dict for ``project``, or None when it is missing or unreadable."""
    path = project_root(workspace, project) / JUDGE_DIR / JUDGEMENT
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def verify_output(input_value, output_value, workspace):
    if not output_value.complete:
        if output_value.recorded or not output_value.next.strip():
            return result(False, "an unfinished judge records nothing and says what to do next")
        return result(True, "judging continues", stages_left=output_value.next)
    if not output_value.recorded or output_value.next.strip():
        return result(False, "a finished judge records the judgement and has nothing next")
    judgement = read_judgement(workspace, input_value.project)
    if judgement is None:
        return result(False, "no readable judgement in the workspace")
    if judgement.get("project") != input_value.project.value or judgement.get("complete") is not True:
        return result(False, "the judgement is for another project or not complete")
    recorded = [entry.get("path") for entry in judgement.get("changed_files", []) if isinstance(entry, dict)]
    if sorted(recorded) != sorted(output_value.changed_files):
        return result(False, "the reported changed files differ from the judgement")
    return result(True, "judgement is recorded", changed_files=len(recorded))
