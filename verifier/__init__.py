"""The deterministic verifier: each tool's checks live in its own module, on contract instances."""

from contract import Task, Tool

from . import judge, list_files, pin, read_file, run_build, run_tests, search, start, sync, task, write_file

TOOLS = {
    Tool.PIN_PROJECT: pin,
    Tool.START_PROJECT: start,
    Tool.LIST_FILES: list_files,
    Tool.READ_FILE: read_file,
    Tool.SEARCH: search,
    Tool.WRITE_FILE: write_file,
    Tool.SYNC: sync,
    Tool.RUN_BUILD: run_build,
    Tool.RUN_TESTS: run_tests,
    Tool.JUDGE: judge,
}
# task -> its outcome check, verify_task(arguments, reference, workspace)
TASKS = {Task.UPGRADE_DEPENDENCY: task.verify_task}


def verify_input(tool, value):
    return TOOLS[Tool(tool)].verify_input(value)


def verify_output(tool, input_value, output_value, workspace):
    return TOOLS[Tool(tool)].verify_output(input_value, output_value, workspace)


def verify_task(task_id, arguments, reference, workspace):
    return TASKS[Task(task_id)](arguments, reference, workspace)
