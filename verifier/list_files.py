from .checks import path_problem, result

MAX_ENTRIES = 200


def verify_input(value):
    problem = path_problem(value.path)
    if problem:
        return result(False, problem)
    if not 1 <= value.max_entries <= MAX_ENTRIES:
        return result(False, f"max_entries must be 1 to {MAX_ENTRIES}")
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    if output_value.path != input_value.path:
        return result(False, "the listing is for another folder")
    if len(output_value.entries) > min(input_value.max_entries, MAX_ENTRIES):
        return result(False, "the listing holds more entries than asked")
    if output_value.truncated != (output_value.total > len(output_value.entries)):
        return result(False, "truncated does not match the counts")
    for entry in output_value.entries:
        if entry.kind not in ("file", "dir") or path_problem(entry.path) or entry.size < 0:
            return result(False, "an entry is malformed")
    return result(True, "listing is well formed", entries=len(output_value.entries))
