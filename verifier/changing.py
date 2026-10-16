"""edit_file and write_file: changes only to an instance's spec file and editable source, all or none,
each followed by the sync and test runs its `then` asked for."""

from pathlib import Path

from . import catalog
from .checks import PREFIX, path_problem, result
from .trees import matches_any

MAX_EDITS = 10
MAX_EDIT_TEXT = 8 * 1024
MAX_FILES = 5
MAX_WRITE = 60 * 1024


def editable_problem(path):
    """Why a workspace-relative path may not be changed by the agent, or None."""
    problem = path_problem(path)
    if problem:
        return problem
    parts = path.split("/")
    if len(parts) < 3 or parts[0] != PREFIX:
        return f"only files inside {PREFIX}/<instance>/ may change"
    try:
        entry = catalog.entry(parts[1])
    except ValueError as error:
        return str(error)
    inside = "/".join(parts[2:])
    if any(part.startswith(".") for part in parts[2:]) or parts[-1] == "conftest.py":
        return f"that file may not change: {inside}"
    if not matches_any(inside, [entry["spec"]["file"], *entry["source_globs"]]):
        return f"{inside} may not change"
    return None


def _then_problem(sync, tests, then):
    if then.value == "nothing" and (sync is not None or tests is not None):
        return "nothing was asked after the change, yet a sync or test result came back"
    if then.value in ("sync", "sync_and_test") and sync is None:
        return "a sync was asked for and none came back"
    if then.value == "sync" and tests is not None:
        return "tests ran although only a sync was asked for"
    if then.value == "sync_and_test" and sync is not None and sync.ok and sync.complete and tests is None:
        return "the tests did not run after a successful sync"
    return None


def verify_edit_input(value):
    if not 1 <= len(value.edits) <= MAX_EDITS:
        return result(False, f"give 1 to {MAX_EDITS} edits per call")
    if sum(len(edit.old.encode("utf-8")) + len(edit.new.encode("utf-8")) for edit in value.edits) > MAX_EDIT_TEXT:
        return result(False, f"the edits hold over {MAX_EDIT_TEXT} bytes of text")
    for edit in value.edits:
        problem = editable_problem(edit.path)
        if problem:
            return result(False, problem)
        if not edit.old:
            return result(False, "old must not be empty")
    return result(True, "input is valid")


def verify_edit_output(input_value, output_value, workspace):
    asked = []
    for edit in input_value.edits:
        if edit.path not in asked:
            asked.append(edit.path)
    if [item.path for item in output_value.edited] != asked:
        return result(False, "the edit reports other files than asked")
    for item in output_value.edited:
        path = Path(workspace) / item.path
        if not path.is_file() or path.stat().st_size != item.bytes:
            return result(False, f"the edited file is not as reported: {item.path}")
        mine = [edit for edit in input_value.edits if edit.path == item.path]
        if item.replacements != len(mine):
            return result(False, f"the replacement count is wrong: {item.path}")
        text = path.read_bytes().decode("utf-8", errors="replace")
        if not all(edit.new in text for edit in mine):
            return result(False, f"a replacement's new text is missing from {item.path}")
    problem = _then_problem(output_value.sync, output_value.tests, input_value.then)
    if problem:
        return result(False, problem)
    return result(True, "files are edited", files=len(output_value.edited))


def verify_write_input(value):
    if not 1 <= len(value.files) <= MAX_FILES:
        return result(False, f"write 1 to {MAX_FILES} files per call")
    paths = [item.path for item in value.files]
    if len(set(paths)) != len(paths):
        return result(False, "a path is given twice")
    total = 0
    for item in value.files:
        problem = editable_problem(item.path)
        if problem:
            return result(False, problem)
        if "\0" in item.content:
            return result(False, "content must be text")
        total += len(item.content.encode("utf-8"))
    if total > MAX_WRITE:
        return result(False, f"the files hold over {MAX_WRITE} bytes")
    return result(True, "input is valid")


def verify_write_output(input_value, output_value, workspace):
    if [item.path for item in output_value.written] != [item.path for item in input_value.files]:
        return result(False, "the write reports other paths than asked")
    for item, made in zip(input_value.files, output_value.written):
        path = Path(workspace) / item.path
        if not path.is_file():
            return result(False, f"the file was not written: {item.path}")
        data = path.read_bytes()
        if data != item.content.encode("utf-8") or made.bytes != len(data):
            return result(False, f"the file does not hold the requested content: {item.path}")
    problem = _then_problem(output_value.sync, output_value.tests, input_value.then)
    if problem:
        return result(False, problem)
    return result(True, "files are written", files=len(output_value.written))
