from .checks import path_problem, result

MAX_LINES = 200
MAX_BYTES = 8 * 1024


def verify_input(value):
    problem = path_problem(value.path)
    if problem:
        return result(False, problem)
    if value.start_line < 1:
        return result(False, "start_line counts from 1")
    if not 1 <= value.max_lines <= MAX_LINES:
        return result(False, f"max_lines must be 1 to {MAX_LINES}")
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    if output_value.path != input_value.path:
        return result(False, "the lines are from another file")
    if len(output_value.lines) > min(input_value.max_lines, MAX_LINES) or output_value.start_line < 1:
        return result(False, "more lines than asked, or a bad start line")
    if output_value.total_lines < 0 or output_value.start_line - 1 + len(output_value.lines) > output_value.total_lines:
        return result(False, "the line counts do not add up")
    if sum(len(line.encode("utf-8")) + 1 for line in output_value.lines) > MAX_BYTES + 1:
        return result(False, f"the lines hold over {MAX_BYTES} bytes")
    return result(True, "lines are well formed", lines=len(output_value.lines))
