"""pin_upgrade, the answer key: read from this instance's catalog entry and PyPI's files for the target
release, which must be the files the instance was validated with."""

from . import catalog
from .checks import is_sha, result


def verify_input(value):
    try:
        catalog.entry(value.instance.value)
    except ValueError as error:
        return result(False, str(error))
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    entry = catalog.entry(input_value.instance.value)
    if output_value.instance != input_value.instance or output_value.catalog_sha256 != catalog.entry_sha256(entry):
        return result(False, "the answer key is not this instance's catalog entry")
    if output_value.dependency != entry["dependency"] or output_value.from_version != entry["from_version"] or output_value.target_version != entry["target_version"]:
        return result(False, "the answer key's dependency or versions are not the catalog's")
    served = sorted((item.filename, item.sha256) for item in output_value.pypi_files)
    expected = sorted((item["filename"], item["sha256"]) for item in entry["target_files"])
    if served != expected or output_value.pypi_yanked:
        return result(False, "PyPI does not serve the target release as validated")
    if output_value.prior_judgement_sha256 and not is_sha(output_value.prior_judgement_sha256):
        return result(False, "the prior judgement's hash is not a sha256")
    return result(True, "the answer key is pinned", files=len(served))
