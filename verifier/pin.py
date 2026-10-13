"""pin_project: the upgrade-dependency reference. Its output is what verify_task holds the task to."""

from .checks import is_sha, is_version, result
from .versions import admits, canonical_name, parse_requirement

HASHES = ("pristine_tree_sha256", "protected_tree_sha256", "pyproject_sha256", "pyproject_rest_sha256", "hidden_tests_sha256")


def verify_input(value):
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    pin = output_value
    if pin.project != input_value.project:
        return result(False, "the pin is for another project")
    if any(not is_sha(digest) for digest in (pin.pristine_tree_sha256, pin.protected_tree_sha256, pin.pyproject_sha256, pin.pyproject_rest_sha256, pin.hidden_tests_sha256)):
        return result(False, "a pinned hash is not a sha256 digest")
    if not is_version(pin.from_version) or not is_version(pin.target_version) or pin.from_version == pin.target_version:
        return result(False, "the pinned versions are not two different versions")
    try:
        requirement = parse_requirement(pin.from_spec)
    except ValueError:
        return result(False, "the pristine requirement is not readable")
    if requirement.name != canonical_name(pin.dependency):
        return result(False, "the pristine requirement names another distribution")
    if not admits(requirement.specifier, pin.from_version) or admits(requirement.specifier, pin.target_version):
        return result(False, "the pristine requirement does not pin the old version short of the target")
    if not pin.hidden_test_ids or len(set(pin.hidden_test_ids)) != len(pin.hidden_test_ids):
        return result(False, "the hidden tests are empty or listed twice")
    if any("::" not in test or not test.startswith("test_hidden_") for test in pin.hidden_test_ids):
        return result(False, "a hidden test id is not test_hidden_<name>.py::<test>")
    if not all(is_version(version) for version in pin.other_dependencies.values()):
        return result(False, "another dependency's locked version is not a version")
    if pin.max_new_files < 0 or pin.max_added_lines <= 0:
        return result(False, "the change limits are not positive")
    if not pin.requires_python.strip() or not pin.package.strip():
        return result(False, "requires-python or the package name is blank")
    return result(True, "the project is pinned", hidden_tests=len(pin.hidden_test_ids), target_version=pin.target_version)
