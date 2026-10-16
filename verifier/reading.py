"""list_files, read_file and search: bounded reads of the workspace, never inside .judge/."""

import re

from .checks import path_problem, result


def verify_list_input(value):
    problem = path_problem(value.path)
    if problem:
        return result(False, problem)
    if not 1 <= value.max_entries <= 200:
        return result(False, "max_entries must be 1 to 200")
    return result(True, "input is valid")


def verify_list_output(input_value, output_value, workspace):
    if len(output_value.entries) > input_value.max_entries or output_value.total < len(output_value.entries):
        return result(False, "the listing is longer than asked or its total is short")
    if output_value.truncated != (output_value.total > len(output_value.entries)):
        return result(False, "truncated must say whether entries stop short of total")
    if any(".judge" in entry.path.split("/") for entry in output_value.entries):
        return result(False, "a listing never shows the judge's folder")
    return result(True, "listing is bounded", entries=len(output_value.entries))


def verify_read_input(value):
    problem = path_problem(value.path)
    if problem:
        return result(False, problem)
    if value.start_line < 1 or not 1 <= value.max_lines <= 200:
        return result(False, "start_line must be at least 1 and max_lines 1 to 200")
    return result(True, "input is valid")


def verify_read_output(input_value, output_value, workspace):
    if len(output_value.lines) > input_value.max_lines:
        return result(False, "more lines came back than asked")
    if sum(len(line.encode("utf-8")) + 1 for line in output_value.lines) > 8 * 1024 + 1:
        return result(False, "a read returns at most 8 KB")
    return result(True, "read is bounded", lines=len(output_value.lines))


def verify_search_input(value):
    problem = path_problem(value.path)
    if problem:
        return result(False, problem)
    if not 1 <= value.max_hits <= 50:
        return result(False, "max_hits must be 1 to 50")
    try:
        re.compile(value.pattern)
    except re.error as error:
        return result(False, f"not a valid regular expression: {error}")
    return result(True, "input is valid")


def verify_search_output(input_value, output_value, workspace):
    if len(output_value.hits) > input_value.max_hits:
        return result(False, "more hits came back than asked")
    if any(len(hit.text) > 200 or ".judge" in hit.path.split("/") for hit in output_value.hits):
        return result(False, "a hit is too long or inside the judge's folder")
    return result(True, "search is bounded", hits=len(output_value.hits))
