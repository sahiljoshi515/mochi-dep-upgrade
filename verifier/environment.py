"""sync and run_tests: the lock and environment as reported, and test counts that add up."""

from . import catalog
from .checks import project_root, result, tail_problem
from .locks import read_lock
from .versions import canonical_name


def verify_sync_input(value):
    try:
        catalog.entry(value.instance.value)
    except ValueError as error:
        return result(False, str(error))
    return result(True, "input is valid")


def verify_sync_output(input_value, output_value, workspace):
    problem = tail_problem(output_value.tail)
    if problem:
        return result(False, problem)
    if not output_value.complete and not output_value.next.strip():
        return result(False, "an unfinished sync must say what to do next")
    if output_value.ok:
        entry = catalog.entry(input_value.instance.value)
        lock = project_root(workspace, entry["id"]) / ".judge" / "requirements.lock"
        if not lock.is_file():
            return result(False, "a successful sync leaves its lock")
        pins = read_lock(lock.read_text(encoding="utf-8")).get(canonical_name(entry["dependency"]), [])
        locked = ",".join(sorted({pin["version"] for pin in pins}))
        if locked != output_value.locked_version or output_value.installed_version != output_value.locked_version:
            return result(False, "the reported locked or installed version is not the lock's")
    return result(True, "sync is consistent", ok=output_value.ok)


def verify_tests_input(value):
    if len(value.tests) > 50:
        return result(False, "at most 50 tests per run")
    for test in value.tests:
        if not test.strip() or test.strip().startswith("-") or ".." in test.split("::", 1)[0].split("/"):
            return result(False, f"not a test path: {test!r}")
    return result(True, "input is valid")


def verify_tests_output(input_value, output_value, workspace):
    problem = tail_problem(output_value.tail)
    if problem:
        return result(False, problem)
    if min(output_value.collected, output_value.passed, output_value.failed, output_value.errors, output_value.skipped, output_value.excluded_failures) < 0:
        return result(False, "counts cannot be negative")
    if len(output_value.failed_ids) > 30:
        return result(False, "at most 30 failed tests are listed")
    return result(True, "test run is consistent", collected=output_value.collected)
