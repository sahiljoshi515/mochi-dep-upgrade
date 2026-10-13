"""verify_task on a synthetic workspace: the gold upgrade is valid at 1.0, and every adversarial
row of the plan is refused with its message. Tool input/output checks at the end."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from slimconfig import build_output
from synthetic import (
    HIDDEN_IDS,
    PACKAGE,
    PROJECT,
    PYPI,
    PYPROJECT,
    TARGET,
    gold_workspace,
    judge_workspace,
    pin_for,
    pristine_files,
    record_of,
    upgraded_files,
    write_judgement,
)

import verifier
from contract import TOOLS, PinOutput, Tool, UpgradeInput

ARGUMENTS = {"project": PROJECT}


def verdict(workspace: Path, pin: dict, arguments: dict = ARGUMENTS) -> dict:
    return verifier.verify_task("upgrade-dependency", build_output(arguments, UpgradeInput), build_output(pin, PinOutput), str(workspace))


def rejudge(root: Path, pin: dict, **overrides) -> None:
    write_judgement(root, judge_workspace(root, pin, **overrides))


def test_gold_upgrade_is_valid(tmp_path: Path):
    workspace, _, pin = gold_workspace(tmp_path)
    found = verdict(workspace, pin)
    assert found["valid"] is True and found["score"] == 1.0
    assert "2.14.1" in found["message"]
    assert all(check["ok"] for check in found["details"]["checks"])
    assert found["details"]["new_files"] == 1
    assert "src/invoicer/settings.py (added)" in found["details"]["changed_files"]


def test_verdict_is_deterministic(tmp_path: Path):
    workspace, _, pin = gold_workspace(tmp_path)
    assert verdict(workspace, pin) == verdict(workspace, pin)


def test_no_judgement_or_wrong_project(tmp_path: Path):
    workspace, root, pin = gold_workspace(tmp_path)
    (root / ".judge" / "judgement.json").unlink()
    found = verdict(workspace, pin)
    assert found["valid"] is False and found["score"] == 0.0 and found["message"] == "no judgement: call judge last"
    rejudge(root, pin, project="ledger-sqlalchemy-2")
    assert "another project" in verdict(workspace, pin)["message"]
    rejudge(root, pin)
    assert "another project" in verdict(workspace, pin_for(tmp_path, project="ledger-sqlalchemy-2"))["message"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("pristine_tree_sha256", "b" * 64, "another pristine project"),
        ("hidden_tests_sha256", "c" * 64, "other hidden tests"),
        ("tree_stable", False, "while the judge was running"),
        ("target_version", "2.13.0", "another upgrade"),
    ],
)
def test_judgement_identity_and_stability(tmp_path: Path, field: str, value, message: str):
    workspace, root, pin = gold_workspace(tmp_path)
    rejudge(root, pin, **{field: value})
    found = verdict(workspace, pin)
    assert found["valid"] is False and found["score"] == 0.0 and message in found["message"]


def test_edits_after_the_judge_are_caught(tmp_path: Path):
    workspace, root, pin = gold_workspace(tmp_path)
    (root / "src" / PACKAGE / "models.py").write_text("# changed later\n")
    found = verdict(workspace, pin)
    assert found["valid"] is False and "after the judge ran" in found["message"]
    # Also a brand-new file nobody judged.
    workspace, root, pin = gold_workspace(tmp_path / "two")
    (root / "src" / PACKAGE / "extra.py").write_text("x = 1\n")
    assert "after the judge ran" in verdict(workspace, pin)["message"]


def test_hand_edited_lock_and_pyproject_are_caught(tmp_path: Path):
    workspace, root, pin = gold_workspace(tmp_path)
    (root / "uv.lock").write_text((root / "uv.lock").read_text() + "\n# tweak\n")
    found = verdict(workspace, pin)
    assert found["valid"] is False and "uv.lock differs" in " ".join(found["details"]["violations"])


def test_spec_bumped_without_relock(tmp_path: Path):
    workspace, root, pin = gold_workspace(tmp_path)
    (root / "uv.lock").write_text(pristine_files()["uv.lock"])
    rejudge(root, pin, lock_check={"ok": False, "tail": ["lock out of date"]}, installed={"pydantic": "1.10.13", "pytest": "9.1.1"})
    found = verdict(workspace, pin)
    assert found["valid"] is False and found["score"] == 0.0
    assert "uv.lock holds pydantic 1.10.13, not 2.14.1" in found["details"]["violations"]


def test_wrong_2x_version(tmp_path: Path):
    workspace, root, pin = gold_workspace(tmp_path)
    (root / "uv.lock").write_text((root / "uv.lock").read_text().replace('version = "2.14.1"', 'version = "2.13.5"'))
    rejudge(root, pin, installed={"pydantic": "2.13.5", "pytest": "9.1.1"})
    found = verdict(workspace, pin)
    assert found["valid"] is False and "uv.lock holds pydantic 2.13.5" in found["message"]


def test_installed_version_must_match_even_with_a_good_lock(tmp_path: Path):
    workspace, root, pin = gold_workspace(tmp_path)
    rejudge(root, pin, installed={"pydantic": "2.13.5", "pytest": "9.1.1"})
    found = verdict(workspace, pin)
    assert found["valid"] is False and found["score"] == 0.75
    assert found["details"]["checks"][1]["message"] == "installed 2.13.5, expected 2.14.1"


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ('git = "https://github.com/pydantic/pydantic?rev=main#abc"', "takes pydantic from outside PyPI"),
        ('registry = "https://example.invalid/simple"', "takes pydantic from outside PyPI"),
    ],
)
def test_alternate_index_or_fork(tmp_path: Path, source: str, message: str):
    workspace, root, pin = gold_workspace(tmp_path)
    (root / "uv.lock").write_text((root / "uv.lock").read_text().replace(PYPI, source, 1).replace(PYPI, source, 1))
    rejudge(root, pin)
    found = verdict(workspace, pin)
    assert found["valid"] is False and message in " ".join(found["details"]["violations"])


def test_url_requirement_is_refused(tmp_path: Path):
    workspace, root, pin = gold_workspace(tmp_path)
    text = (root / "pyproject.toml").read_text().replace('"pydantic==2.14.1",', '"pydantic @ https://example.invalid/pydantic-2.14.1.whl",')
    (root / "pyproject.toml").write_text(text)
    rejudge(root, pin)
    found = verdict(workspace, pin)
    assert found["valid"] is False and "points at a URL" in " ".join(found["details"]["violations"])


@pytest.mark.parametrize(
    ("deps", "message"),
    [
        ('"pydantic>=1.10",', "still admits 1.10.13"),
        ('"pydantic",', "does not admit 2.14.1"),
        ('"pydantic==2.13.5",', "does not admit 2.14.1"),
        ('"pydantic-settings>=2.10",', "must be required exactly once"),
        ('"pydantic==2.14.1",\n    "pydantic==2.14.1",', "listed twice"),
        ('"pydantic==2.14.1 ; python_version < \\"4\\"",', "unconditionally"),
        ('"pydantic==2.14.1",\n    "requests>=2",', "requirement added that is not allowed: requests"),
        ('"pydantic==2.14.1",\n    "pydantic-settings>=2.10",\n    "pytest>=9",', "requirement added that is not allowed: pytest"),
    ],
)
def test_requirement_rules(tmp_path: Path, deps: str, message: str):
    workspace, root, pin = gold_workspace(tmp_path)
    (root / "pyproject.toml").write_text(PYPROJECT.format(deps=deps))
    rejudge(root, pin)
    found = verdict(workspace, pin)
    assert found["valid"] is False and found["score"] == 0.0
    assert message in " ".join(found["details"]["violations"])


def test_collateral_pins_and_removed_requirements(tmp_path: Path):
    workspace, root, pin = gold_workspace(tmp_path)
    pin = pin_for(tmp_path, pristine_dependencies=["pydantic>=1.10.13,<2", "click>=8"], other_dependencies={"pytest": "9.1.1", "click": "8.1.7"})
    # Pristine required click as well; the upgrade changed its requirement and the lock moved it.
    (root / "pyproject.toml").write_text(PYPROJECT.format(deps='"pydantic==2.14.1",\n    "click>=9",'))
    rejudge(root, pin)
    found = verdict(workspace, pin)
    violations = " ".join(found["details"]["violations"])
    assert "requirement changed: click" in violations and "locked version changed: click" in violations
    # Dropping it instead.
    (root / "pyproject.toml").write_text(PYPROJECT.format(deps='"pydantic==2.14.1",'))
    rejudge(root, pin)
    assert "requirement removed: click" in " ".join(verdict(workspace, pin)["details"]["violations"])
    # Allowed as collateral: the requirement may change, but the lock still has to hold it.
    allowed = pin_for(tmp_path, pristine_dependencies=["pydantic>=1.10.13,<2", "click>=8"], other_dependencies={"pytest": "9.1.1", "click": "8.1.7"}, allowed_collateral=["click"])
    (root / "pyproject.toml").write_text(PYPROJECT.format(deps='"pydantic==2.14.1",\n    "click>=9",'))
    rejudge(root, allowed)
    assert "click" not in " ".join(verdict(workspace, allowed)["details"]["violations"])


def test_requires_python_and_other_pyproject_edits(tmp_path: Path):
    workspace, root, pin = gold_workspace(tmp_path)
    text = (root / "pyproject.toml").read_text()
    (root / "pyproject.toml").write_text(text.replace('requires-python = ">=3.12"', 'requires-python = ">=3.13"'))
    rejudge(root, pin)
    violations = " ".join(verdict(workspace, pin)["details"]["violations"])
    assert "requires-python changed" in violations and "outside its [project] dependencies array" in violations
    (root / "pyproject.toml").write_text(text + '\n[tool.pytest.ini_options]\nfilterwarnings = ["ignore"]\n')
    rejudge(root, pin)
    assert "outside its [project] dependencies array" in " ".join(verdict(workspace, pin)["details"]["violations"])


def test_protected_files_and_disallowed_paths(tmp_path: Path):
    workspace, root, pin = gold_workspace(tmp_path)
    (root / "tests" / "test_models.py").write_text("def test_nothing():\n    pass\n")
    rejudge(root, pin)
    found = verdict(workspace, pin)
    assert "tests/ or README.md differ" in " ".join(found["details"]["violations"])
    assert "file may not change: tests/test_models.py" in found["details"]["violations"]
    workspace, root, pin = gold_workspace(tmp_path / "readme")
    (root / "README.md").write_text("# changed\n")
    rejudge(root, pin)
    assert "tests/ or README.md differ" in " ".join(verdict(workspace, pin)["details"]["violations"])
    workspace, root, pin = gold_workspace(tmp_path / "ci")
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / ".github" / "workflows" / "ci.yml").write_text("on: push\n")
    (root / "src" / "other" / "x.py").parent.mkdir(parents=True)
    (root / "src" / "other" / "x.py").write_text("x = 1\n")
    rejudge(root, pin)
    violations = verdict(workspace, pin)["details"]["violations"]
    assert "file may not change: .github/workflows/ci.yml" in violations
    assert "file may not change: src/other/x.py" in violations


def test_deleted_files_and_limits(tmp_path: Path):
    workspace, root, pin = gold_workspace(tmp_path)
    (root / "src" / PACKAGE / "__init__.py").unlink()
    rejudge(root, pin)
    assert "file removed: src/invoicer/__init__.py" in verdict(workspace, pin)["details"]["violations"]
    workspace, root, pin = gold_workspace(tmp_path / "many")
    for number in range(6):
        (root / "src" / PACKAGE / f"new{number}.py").write_text("x = 1\n")
    rejudge(root, pin)
    assert "7 new files, over the limit of 5" in verdict(workspace, pin)["details"]["violations"]
    workspace, root, pin = gold_workspace(tmp_path / "long")
    (root / "src" / PACKAGE / "big.py").write_text("x = 1\n" * 700)
    rejudge(root, pin)
    assert "added lines, over the limit of 600" in " ".join(verdict(workspace, pin)["details"]["violations"])


@pytest.mark.parametrize(
    "shim",
    [
        "from pydantic.v1 import BaseModel\n",
        "import warnings\nwarnings.filterwarnings('ignore', category=DeprecationWarning)\n",
        "import sys\nsys.modules['pydantic'] = None\n",
        "import pydantic\npydantic.BaseModel.dict = lambda self: {}\n",
        "import pytest\n",
    ],
)
def test_forbidden_patterns_in_source(tmp_path: Path, shim: str):
    workspace, root, pin = gold_workspace(tmp_path)
    (root / "src" / PACKAGE / "compat.py").write_text(shim)
    rejudge(root, pin)  # the judge recorded nothing: the verifier scans on its own
    found = verdict(workspace, pin)
    assert found["valid"] is False and found["score"] == 0.0
    assert any("forbidden pattern: src/invoicer/compat.py" in item for item in found["details"]["violations"])


def test_forbidden_recorded_by_the_judge(tmp_path: Path):
    workspace, root, pin = gold_workspace(tmp_path)
    rejudge(root, pin, forbidden=["src/invoicer/models.py:1: something"])
    assert "forbidden pattern: src/invoicer/models.py:1: something" in verdict(workspace, pin)["details"]["violations"]


def test_outcomes_score_a_quarter_each(tmp_path: Path):
    workspace, root, pin = gold_workspace(tmp_path)
    rejudge(root, pin, build={"ok": False, "wheel": "", "tail": ["boom"], "seconds": 1.0})
    found = verdict(workspace, pin)
    assert found["valid"] is False and found["score"] == 0.75 and "Wheel builds" in found["message"]
    rejudge(root, pin, public=record_of(["tests/test_models.py::test_number"], failed=["tests/test_models.py::test_number"]))
    found = verdict(workspace, pin)
    assert found["score"] == 0.75 and found["details"]["failed_tests"]["public"] == ["tests/test_models.py::test_number"]
    rejudge(root, pin, hidden=record_of(HIDDEN_IDS, failed=[HIDDEN_IDS[1]]))
    found = verdict(workspace, pin)
    assert found["score"] == 0.75 and found["details"]["failed_tests"]["hidden"] == [HIDDEN_IDS[1]]
    rejudge(root, pin, lock_check={"ok": False, "tail": []}, build={"ok": False, "wheel": "", "tail": [], "seconds": 0}, public=record_of([]), hidden=record_of([]))
    found = verdict(workspace, pin)
    assert found["valid"] is False and found["score"] == 0.0 and found["message"].startswith("not done")


def test_hidden_tests_must_be_exactly_the_pinned_set(tmp_path: Path):
    workspace, root, pin = gold_workspace(tmp_path)
    rejudge(root, pin, hidden=record_of(HIDDEN_IDS[:1]))
    assert verdict(workspace, pin)["score"] == 0.75
    rejudge(root, pin, hidden=record_of(HIDDEN_IDS + ["test_hidden_api.py::test_extra"]))
    assert verdict(workspace, pin)["score"] == 0.75
    rejudge(root, pin, hidden=record_of(HIDDEN_IDS, collection_errors={"test_hidden_api.py": "ImportError"}))
    assert verdict(workspace, pin)["score"] == 0.75
    rejudge(root, pin, hidden=record_of(HIDDEN_IDS, exit_status=2))
    assert verdict(workspace, pin)["score"] == 0.75


def test_forged_changed_files_list_is_caught(tmp_path: Path):
    workspace, root, pin = gold_workspace(tmp_path)
    # A judgement that lists fewer files than changed: the whole-tree hash is consistent only with
    # what the judge saw, and here the tree holds a file the list omits.
    rejudge(root, pin, changed_override=[])
    found = verdict(workspace, pin)
    assert found["valid"] is True  # nothing contradicts the tree: the list is informational...
    (root / "src" / PACKAGE / "sneaky.py").write_text("from pydantic.v1 import BaseModel\n")
    rejudge(root, pin, changed_override=[])
    found = verdict(workspace, pin)  # ...but the verifier's own scan still reads every source file
    assert found["valid"] is False and any("forbidden pattern: src/invoicer/sneaky.py" in item for item in found["details"]["violations"])


# ----- tool checks -----


def check_input(tool: str, value: dict) -> dict:
    return verifier.verify_input(tool, build_output(value, TOOLS[Tool(tool)][0]))


def check_output(tool: str, value: dict, output: dict, workspace: Path) -> dict:
    given, made = TOOLS[Tool(tool)]
    return verifier.verify_output(tool, build_output(value, given), build_output(output, made), str(workspace))


def test_path_inputs_are_confined():
    assert check_input("read_file", {"path": "dep-upgrade/x/src/a.py", "start_line": 1, "max_lines": 200})["valid"] is True
    assert check_input("read_file", {"path": "/etc/passwd", "start_line": 1, "max_lines": 10})["valid"] is False
    assert check_input("read_file", {"path": "dep-upgrade/../x", "start_line": 1, "max_lines": 10})["valid"] is False
    assert check_input("read_file", {"path": "dep-upgrade/x/.judge/judgement.json", "start_line": 1, "max_lines": 10})["valid"] is False
    assert check_input("read_file", {"path": "dep-upgrade/x/a.py", "start_line": 0, "max_lines": 10})["valid"] is False
    assert check_input("read_file", {"path": "dep-upgrade/x/a.py", "start_line": 1, "max_lines": 201})["valid"] is False
    assert check_input("list_files", {"path": "dep-upgrade/x", "max_entries": 0})["valid"] is False
    assert check_input("search", {"path": "dep-upgrade/x", "pattern": "(", "glob": "*.py", "max_hits": 10})["valid"] is False
    assert check_input("search", {"path": "dep-upgrade/x", "pattern": "x", "glob": "", "max_hits": 10})["valid"] is False
    assert check_input("search", {"path": "dep-upgrade/x", "pattern": "x", "glob": "*.py", "max_hits": 51})["valid"] is False
    assert check_input("run_tests", {"project": PROJECT, "tests": ["-k", "x"]})["valid"] is False
    assert check_input("run_tests", {"project": PROJECT, "tests": ["src/invoicer/models.py"]})["valid"] is False
    assert check_input("run_tests", {"project": PROJECT, "tests": ["tests/test_models.py::test_number"]})["valid"] is True


@pytest.mark.parametrize(
    ("path", "ok"),
    [
        ("dep-upgrade/invoicer-pydantic-2/pyproject.toml", True),
        ("dep-upgrade/invoicer-pydantic-2/src/invoicer/models.py", True),
        ("dep-upgrade/invoicer-pydantic-2/src/invoicer/sub/deep.py", True),
        ("dep-upgrade/invoicer-pydantic-2/tests/test_models.py", False),
        ("dep-upgrade/invoicer-pydantic-2/uv.lock", False),
        ("dep-upgrade/invoicer-pydantic-2/README.md", False),
        ("dep-upgrade/invoicer-pydantic-2/src/invoicer/data.json", False),
        ("dep-upgrade/invoicer-pydantic-2/src/invoicer/conftest.py", False),
        ("dep-upgrade/invoicer-pydantic-2/.judge/judgement.json", False),
        ("pyproject.toml", False),
    ],
)
def test_write_paths(path: str, ok: bool):
    assert check_input("write_file", {"files": [{"path": path, "content": "x = 1\n"}]})["valid"] is ok


def test_write_batches_are_bounded():
    good = "dep-upgrade/invoicer-pydantic-2/src/invoicer/m{}.py"
    assert check_input("write_file", {"files": []})["valid"] is False
    assert check_input("write_file", {"files": [{"path": good.format(n), "content": "x = 1\n"} for n in range(6)]})["valid"] is False
    assert check_input("write_file", {"files": [{"path": good.format(1), "content": "x = 1\n"}, {"path": good.format(1), "content": "y = 2\n"}]})["valid"] is False
    assert check_input("write_file", {"files": [{"path": good.format(1), "content": "#" * (60 * 1024 + 1)}]})["valid"] is False
    assert check_input("write_file", {"files": [{"path": good.format(n), "content": "x = 1\n"} for n in range(5)]})["valid"] is True


def test_write_output_must_match_the_files(tmp_path: Path):
    first = "dep-upgrade/invoicer-pydantic-2/src/invoicer/models.py"
    second = "dep-upgrade/invoicer-pydantic-2/pyproject.toml"
    for path, text in ((first, "x = 1\n"), (second, "[project]\n")):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    given = {"files": [{"path": first, "content": "x = 1\n"}, {"path": second, "content": "[project]\n"}]}
    good = {"written": [{"path": first, "bytes": 6}, {"path": second, "bytes": 10}]}
    assert check_output("write_file", given, good, tmp_path)["valid"] is True
    assert check_output("write_file", given, {"written": [{"path": first, "bytes": 6}]}, tmp_path)["valid"] is False
    assert check_output("write_file", given, {"written": [{"path": first, "bytes": 7}, {"path": second, "bytes": 10}]}, tmp_path)["valid"] is False
    (tmp_path / first).write_text("x = 2\n")
    assert check_output("write_file", given, good, tmp_path)["valid"] is False


def test_pin_output_checks(tmp_path: Path):
    pin = pin_for(tmp_path)
    assert check_output("pin_project", ARGUMENTS, pin, tmp_path)["valid"] is True
    assert check_output("pin_project", {"project": "ledger-sqlalchemy-2"}, pin, tmp_path)["valid"] is False
    assert check_output("pin_project", ARGUMENTS, {**pin, "from_spec": "pydantic>=1,<3"}, tmp_path)["valid"] is False
    assert check_output("pin_project", ARGUMENTS, {**pin, "hidden_test_ids": []}, tmp_path)["valid"] is False
    assert check_output("pin_project", ARGUMENTS, {**pin, "target_version": "latest"}, tmp_path)["valid"] is False


def test_judge_output_checks(tmp_path: Path):
    workspace, root, _pin = gold_workspace(tmp_path)
    recorded = json.loads((root / ".judge" / "judgement.json").read_text())
    output = {
        "recorded": True,
        "complete": True,
        "next": "",
        "changed_files": [entry["path"] for entry in recorded["changed_files"]],
        "protected_changes": [],
        "lock_ok": True,
        "installed_version": TARGET,
        "build_ok": True,
        "public_passed": 1,
        "public_failed": 0,
        "violations": [],
        "seconds": 10.0,
    }
    assert check_output("judge", ARGUMENTS, output, workspace)["valid"] is True
    assert check_output("judge", ARGUMENTS, {**output, "changed_files": []}, workspace)["valid"] is False
    assert check_output("judge", {"project": "ledger-sqlalchemy-2"}, output, workspace)["valid"] is False
    assert check_output("judge", ARGUMENTS, {**output, "next": "again"}, workspace)["valid"] is False
    paused = {**output, "recorded": False, "complete": False, "next": "call judge again to continue: the hidden tests are left"}
    assert check_output("judge", ARGUMENTS, paused, workspace)["valid"] is True
    assert check_output("judge", ARGUMENTS, {**paused, "recorded": True}, workspace)["valid"] is False
    assert check_output("judge", ARGUMENTS, {**paused, "next": ""}, workspace)["valid"] is False


def test_incomplete_judgement_is_refused(tmp_path: Path):
    workspace, root, pin = gold_workspace(tmp_path)
    rejudge(root, pin, complete=False)
    found = verdict(workspace, pin)
    assert found["valid"] is False and found["score"] == 0.0 and "did not finish" in found["message"]


def test_start_output_checks(tmp_path: Path):
    workspace, _, _ = gold_workspace(tmp_path)
    output = {
        "root": f"dep-upgrade/{PROJECT}",
        "complete": True,
        "next": "",
        "dependency": "pydantic",
        "current_version": "1.10.13",
        "target_version": TARGET,
        "package": PACKAGE,
        "uses_dependency": ["src/invoicer/models.py"],
        "layout": ["pyproject.toml"],
        "allowed_new_dependencies": [],
        "allowed_collateral": [],
        "rules": ["r"],
        "build_hint": "b",
        "test_hint": "t",
    }
    assert check_output("start_project", ARGUMENTS, output, workspace)["valid"] is True
    assert check_output("start_project", ARGUMENTS, {**output, "root": "elsewhere"}, workspace)["valid"] is False
    assert check_output("start_project", ARGUMENTS, {**output, "current_version": TARGET}, workspace)["valid"] is False
    assert check_output("start_project", ARGUMENTS, {**output, "next": "again"}, workspace)["valid"] is False
    paused = {**output, "complete": False, "next": "call start_project again", "current_version": ""}
    assert check_output("start_project", ARGUMENTS, paused, workspace)["valid"] is True
    assert check_output("start_project", ARGUMENTS, {**paused, "next": ""}, workspace)["valid"] is False
    assert check_output("start_project", ARGUMENTS, {**output, "layout": ["f"] * 41}, workspace)["valid"] is False


def test_upgraded_files_differ_from_pristine_only_where_expected():
    assert set(upgraded_files()) - set(pristine_files()) == {f"src/{PACKAGE}/settings.py"}
