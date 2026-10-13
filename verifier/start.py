"""start_project: the project copied and committed under dep-upgrade/<project>/ and its environment
installed outside the workspace, in one call or several (``complete: false`` asks for another call)."""

from pathlib import Path

from .checks import PREFIX, is_version, result

MAX_LAYOUT = 40
MAX_USES = 20


def verify_input(value):
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    expected = f"{PREFIX}/{input_value.project.value}"
    if output_value.root != expected:
        return result(False, f"the project root must be {expected}")
    root = Path(workspace) / output_value.root
    if not (root / "pyproject.toml").is_file() or not (root / "src").is_dir() or not (root / "tests").is_dir():
        return result(False, "the project is not set up in the workspace")
    if len(output_value.layout) > MAX_LAYOUT or len(output_value.uses_dependency) > MAX_USES:
        return result(False, "the layout or the dependency uses are too long")
    if not is_version(output_value.target_version) or not output_value.package.strip() or not output_value.rules:
        return result(False, "the target version, package or rules are blank")
    if not output_value.complete:
        if not output_value.next.strip():
            return result(False, "an unfinished start must say what to do next")
        return result(True, "the project is being set up", root=output_value.root)
    if output_value.next.strip():
        return result(False, "a finished start has nothing next")
    if not is_version(output_value.current_version) or output_value.current_version == output_value.target_version:
        return result(False, "the current version is not a version short of the target")
    if not output_value.layout:
        return result(False, "the project is not installed")
    return result(True, "the project is set up", root=output_value.root)
