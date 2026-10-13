from pathlib import Path

from .checks import WRITABLE, path_problem, result

MAX_FILES = 5
MAX_WRITE = 60 * 1024


def verify_input(value):
    if not 1 <= len(value.files) <= MAX_FILES:
        return result(False, f"write 1 to {MAX_FILES} files per call")
    paths = [item.path for item in value.files]
    if len(set(paths)) != len(paths):
        return result(False, "a path is given twice")
    total = 0
    for item in value.files:
        problem = path_problem(item.path)
        if problem:
            return result(False, problem)
        if not WRITABLE.fullmatch(item.path):
            return result(False, "only dep-upgrade/<project>/pyproject.toml or a .py file under dep-upgrade/<project>/src/<package>/ may be written")
        if Path(item.path).name == "conftest.py":
            return result(False, "conftest.py may not be written")
        if "\0" in item.content:
            return result(False, "content must be text")
        total += len(item.content.encode("utf-8"))
    if total > MAX_WRITE:
        return result(False, f"the files hold over {MAX_WRITE} bytes")
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    if [item.path for item in output_value.written] != [item.path for item in input_value.files]:
        return result(False, "the write reports other paths than asked")
    for item, made in zip(input_value.files, output_value.written):
        path = Path(workspace) / item.path
        if not path.is_file():
            return result(False, f"the file was not written: {item.path}")
        data = path.read_bytes()
        if data != item.content.encode("utf-8"):
            return result(False, f"the file does not hold the requested content: {item.path}")
        if made.bytes != len(data):
            return result(False, f"the reported size is wrong: {item.path}")
    return result(True, "files are written", files=len(output_value.written))
