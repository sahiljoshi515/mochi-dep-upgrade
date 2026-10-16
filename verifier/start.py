"""start_upgrade: the repository checked out at the commit before its upgrade, its pristine record
matching the catalog's tree hash, and its pre-upgrade environment installed (in one call or several)."""

from . import catalog
from .checks import PREFIX, project_root, result
from .shims import pristine_manifest
from .trees import tree_hash


def verify_input(value):
    try:
        catalog.entry(value.instance.value)
    except ValueError as error:
        return result(False, str(error))
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    instance = input_value.instance.value
    entry = catalog.entry(instance)
    if output_value.root != f"{PREFIX}/{instance}":
        return result(False, f"the project root must be {PREFIX}/{instance}")
    if output_value.dependency != entry["dependency"] or output_value.target_version != entry["target_version"] or output_value.spec_file != entry["spec"]["file"]:
        return result(False, "the start names another dependency, target or spec file than the catalog")
    if len(output_value.uses) > 20 or len(output_value.breaking) > 10 or len(output_value.excluded_tests) > 20:
        return result(False, "the start's lists are longer than their caps")
    root = project_root(workspace, instance)
    manifest = pristine_manifest(root)
    if manifest is None or tree_hash(manifest["files"].items()) != entry["base"]["tree_sha256"]:
        return result(False, "the pristine record is missing or is not the validated tree")
    if not output_value.complete:
        if not output_value.next.strip():
            return result(False, "an unfinished start must say what to do next")
        return result(True, "the project is being set up", root=output_value.root)
    if output_value.next.strip():
        return result(False, "a finished start has nothing next")
    if output_value.current_version != entry["from_version"]:
        return result(False, f"the start reports {output_value.current_version!r} installed, not {entry['from_version']}")
    if not (root / ".judge" / "ready.json").is_file() or not (root / ".judge" / "requirements.lock").is_file():
        return result(False, "a finished start leaves its ready record and lock")
    return result(True, "the project is set up", root=output_value.root, files=len(manifest["files"]))
