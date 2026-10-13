from pathlib import Path

from .checks import result, tail_problem

MAX_TARGETS = 50


def verify_input(value):
    if len(value.tests) > MAX_TARGETS:
        return result(False, f"at most {MAX_TARGETS} tests per run")
    for target in value.tests:
        file_part = target.split("::", 1)[0]
        if not target.strip() or target.startswith("-") or "\0" in target or Path(file_part).is_absolute() or ".." in Path(file_part).parts:
            return result(False, f"not a test path: {target!r}")
        if file_part != "tests" and not file_part.startswith("tests/"):
            return result(False, "tests live under tests/")
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    problem = tail_problem(output_value.tail)
    if problem:
        return result(False, problem)
    counts = (output_value.collected, output_value.passed, output_value.failed, output_value.errors, output_value.skipped)
    if any(count < 0 for count in counts) or output_value.seconds < 0:
        return result(False, "a count is negative")
    if output_value.passed > output_value.collected or len(output_value.failed_ids) > 50:
        return result(False, "the counts do not add up")
    return result(True, "tests reported", passed=output_value.passed, failed=output_value.failed)
