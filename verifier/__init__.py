"""The deterministic verifier: each tool's checks live in its own module, on contract instances."""

from contract import Task, Tool

from . import changing, environment, judge, pin, reading, start, task


class Pair:
    def __init__(self, check_input, check_output):
        self.verify_input = check_input
        self.verify_output = check_output


TOOLS = {
    Tool.PIN_UPGRADE: pin,
    Tool.START_UPGRADE: start,
    Tool.LIST_FILES: Pair(reading.verify_list_input, reading.verify_list_output),
    Tool.READ_FILE: Pair(reading.verify_read_input, reading.verify_read_output),
    Tool.SEARCH: Pair(reading.verify_search_input, reading.verify_search_output),
    Tool.EDIT_FILE: Pair(changing.verify_edit_input, changing.verify_edit_output),
    Tool.WRITE_FILE: Pair(changing.verify_write_input, changing.verify_write_output),
    Tool.SYNC: Pair(environment.verify_sync_input, environment.verify_sync_output),
    Tool.RUN_TESTS: Pair(environment.verify_tests_input, environment.verify_tests_output),
    Tool.JUDGE: judge,
}
# task -> its output's check, verify_task(arguments, output, reference, workspace)
TASKS = {Task.UPGRADE_DEPENDENCY: task.verify_task}


def verify_input(tool, value):
    return TOOLS[Tool(tool)].verify_input(value)


def verify_output(tool, input_value, output_value, workspace):
    return TOOLS[Tool(tool)].verify_output(input_value, output_value, workspace)


def verify_task(task_id, arguments, output, reference, workspace):
    return TASKS[Task(task_id)](arguments, output, reference, workspace)
