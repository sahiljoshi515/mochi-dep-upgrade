import re

from .checks import path_problem, result

MAX_HITS = 50
MAX_PATTERN = 300


def verify_input(value):
    problem = path_problem(value.path)
    if problem:
        return result(False, problem)
    if not value.pattern.strip() or len(value.pattern) > MAX_PATTERN:
        return result(False, f"pattern must be 1 to {MAX_PATTERN} characters")
    try:
        re.compile(value.pattern)
    except re.error as error:
        return result(False, f"pattern is not a regular expression: {error}")
    if not value.glob.strip() or len(value.glob) > 100 or "\0" in value.glob:
        return result(False, "glob must name files, e.g. *.py")
    if not 1 <= value.max_hits <= MAX_HITS:
        return result(False, f"max_hits must be 1 to {MAX_HITS}")
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    if len(output_value.hits) > min(input_value.max_hits, MAX_HITS):
        return result(False, "more hits than asked")
    if output_value.files_searched < 0:
        return result(False, "files_searched is negative")
    for hit in output_value.hits:
        if path_problem(hit.path) or hit.line < 1:
            return result(False, "a hit is malformed")
    return result(True, "hits are well formed", hits=len(output_value.hits))
