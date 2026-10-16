"""The upgrade-dependency verdict on a synthetic instance: the upgrade done right holds on every one of
the 19 constraints; each way of getting it wrong fails exactly where it should, with a plain
message, and never scores 1.0. Also the tools' input and output checks."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest
import synthetic as s

import verifier
from contract import Edit, EditInput, InstanceId, JudgeOutput, Then, UpgradeInput
from verifier import catalog
from verifier.changing import editable_problem

ORDER = [
    "instance_pinned",
    "submitted_facts",
    "migration_notes",
    "judged",
    "judged_this_run",
    "judgement_consistent",
    "files_as_judged",
    "submission_matches",
    "allowed_files_only",
    "within_limits",
    "spec_scope",
    "spec_admits_target",
    "lock_target",
    "lock_scope",
    "installed_target",
    "builds",
    "public_tests_pass",
    "hidden_tests_pass",
    "no_shims",
]


def upgraded(workspace: Path, item: dict, files: dict | None = None) -> Path:
    root = s.started_workspace(workspace, item)
    s.write_project(root, s.UPGRADED if files is None else files)
    return root


def verdict(workspace: Path, item: dict, *, submission=None, pin=None) -> dict:
    first = verifier.verify_task("upgrade-dependency", s.arguments(), submission or s.submission(), pin or s.pin(item), str(workspace))
    second = verifier.verify_task("upgrade-dependency", s.arguments(), submission or s.submission(), pin or s.pin(item), str(workspace))
    assert json.dumps(first, sort_keys=True, default=str) == json.dumps(second, sort_keys=True, default=str)
    return first


def failed(result: dict) -> list[str]:
    return [item["id"] for item in result["details"]["constraints"] if item["ok"] is False]


def by_id(result: dict) -> dict:
    return {item["id"]: item for item in result["details"]["constraints"]}


def test_the_upgrade_done_right_holds_on_all_19_constraints(tmp_path: Path, demo: dict):
    root = upgraded(tmp_path, demo)
    s.judged(root, demo)
    result = verdict(tmp_path, demo)
    assert [item["id"] for item in result["details"]["constraints"]] == ORDER
    assert result["valid"] is True and result["score"] == 1.0
    assert result["message"].startswith("All 19 checks hold")
    assert result["details"]["changed_files"] == ["demo/core.py", "setup.py"]
    assert any(line.startswith("+++ b/demo/core.py") for line in result["details"]["diff"])


def judged_wrongly(tmp_path, demo, **override):
    root = upgraded(tmp_path, demo)
    s.judged(root, demo, **override)
    return root


CASES = {
    "instance_pinned": lambda t, d: verdict(t, d, pin=dataclasses.replace(s.pin(d), pypi_yanked=True)),
    "submitted_facts": lambda t, d: verdict(t, d, submission=s.submission(to_version="0.28.0")),
    "migration_notes": lambda t, d: verdict(t, d, submission=s.submission(migration=["too short"])),
    "judgement_consistent": lambda t, d: verdict(t, d) if judged_wrongly(t, d, catalog_sha256="0" * 64) else None,
    "public_tests_pass": lambda t, d: verdict(t, d) if judged_wrongly(t, d, public={"ran": True, "ok": False, "ids_sha256": catalog.ids_sha256(d["public"]["ids"]), "passed": 0, "failed": ["tests/test_core.py::test_answer"], "failed_count": 1, "missing": [], "missing_count": 0}) else None,
    "hidden_tests_pass": lambda t, d: verdict(t, d) if judged_wrongly(t, d, hidden={"ran": True, "ok": True, "ids_sha256": "0" * 64, "passed": 1, "failed": [], "failed_count": 0, "missing": [], "missing_count": 0, "files_digest": catalog.hidden_digest(d["hidden"]["files"])}) else None,
    "installed_target": lambda t, d: verdict(t, d) if judged_wrongly(t, d, install={"ok": True, "installed": {"httpx": "0.27.2"}, "pip_check": {"ok": True}}) else None,
    "builds": lambda t, d: verdict(t, d) if judged_wrongly(t, d, build={"ok": True, "wheel": "demo.whl", "requires_dist": ["httpx<0.28", "six"]}) else None,
}


@pytest.mark.parametrize("constraint", sorted(CASES))
def test_each_judgement_or_submission_fault_fails_exactly_its_constraint(tmp_path: Path, demo: dict, constraint: str):
    if constraint in ("instance_pinned", "submitted_facts", "migration_notes"):
        s.judged(upgraded(tmp_path, demo), demo)
    result = CASES[constraint](tmp_path, demo)
    assert failed(result) == [constraint]
    assert result["valid"] is False and result["score"] < 1.0
    assert result["message"].startswith("1 of 19 checks failed. First: ")


def test_no_judgement_leaves_what_needs_one_unchecked(tmp_path: Path, demo: dict):
    upgraded(tmp_path, demo)
    result = verdict(tmp_path, demo)
    checks = by_id(result)
    assert checks["judged"]["ok"] is False and "No judgement" in result["message"]
    for cid in ("judged_this_run", "judgement_consistent", "files_as_judged", "lock_target", "lock_scope", "installed_target", "builds", "public_tests_pass", "hidden_tests_pass"):
        assert checks[cid]["ok"] is None and checks[cid]["message"].startswith("not checked")
    for cid in ("submission_matches", "allowed_files_only", "within_limits", "spec_scope", "spec_admits_target", "no_shims"):
        assert checks[cid]["ok"] is True, cid
    assert result["score"] < 1.0


def test_an_unfinished_judgement_is_not_a_judgement(tmp_path: Path, demo: dict):
    judged_wrongly(tmp_path, demo, complete=False)
    result = verdict(tmp_path, demo)
    assert "Judging did not finish" in result["message"]


def test_an_earlier_runs_judgement_does_not_count(tmp_path: Path, demo: dict):
    root = judged_wrongly(tmp_path, demo)
    prior = hashlib.sha256((root / ".judge" / "judgement.json").read_bytes()).hexdigest()
    result = verdict(tmp_path, demo, pin=s.pin(demo, prior=prior))
    assert failed(result) == ["judged_this_run"] and "from an earlier run" in result["message"]


def test_a_judgement_from_another_set_up_does_not_count(tmp_path: Path, demo: dict):
    judged_wrongly(tmp_path, demo, setup_token="forged")
    result = verdict(tmp_path, demo)
    assert failed(result) == ["judged_this_run"] and "does not belong to this set-up" in result["message"]


def test_a_change_after_judging_is_caught(tmp_path: Path, demo: dict):
    root = judged_wrongly(tmp_path, demo)
    (root / "demo" / "core.py").write_text((root / "demo" / "core.py").read_text() + "# later\n")
    result = verdict(tmp_path, demo)
    assert "files_as_judged" in failed(result)
    assert by_id(result)["files_as_judged"]["message"] == "demo/core.py changed after the judge ran"


def test_an_unstable_judgement_is_caught(tmp_path: Path, demo: dict):
    judged_wrongly(tmp_path, demo, tree_stable=False)
    assert failed(verdict(tmp_path, demo)) == ["files_as_judged"]


def test_the_submission_must_list_exactly_the_changed_files(tmp_path: Path, demo: dict):
    judged_wrongly(tmp_path, demo)
    result = verdict(tmp_path, demo, submission=s.submission(changed_files=["demo/core.py"]))
    assert failed(result) == ["submission_matches"] and "leaves out changed files: setup.py" in result["message"]
    result = verdict(tmp_path, demo, submission=s.submission(changed_files=["demo/core.py", "setup.py", "demo/__init__.py"]))
    assert "lists files that did not change: demo/__init__.py" in result["message"]


def test_the_submission_must_state_the_specs_requirement(tmp_path: Path, demo: dict):
    judged_wrongly(tmp_path, demo)
    assert failed(verdict(tmp_path, demo, submission=s.submission(requirement="httpx>=0.28"))) == ["submission_matches"]
    assert verdict(tmp_path, demo, submission=s.submission(requirement="HTTPX >= 0.25.0"))["valid"] is True


def test_tests_may_not_change(tmp_path: Path, demo: dict):
    root = upgraded(tmp_path, demo)
    (root / "tests" / "test_core.py").write_text("def test_answer():\n    assert True\n")
    s.judged(root, demo)
    result = verdict(tmp_path, demo, submission=s.submission(changed_files=["demo/core.py", "setup.py", "tests/test_core.py"]))
    assert failed(result) == ["allowed_files_only"] and result["message"].endswith("tests/test_core.py may not change")


def test_deleting_a_file_is_not_an_upgrade(tmp_path: Path, demo: dict):
    root = upgraded(tmp_path, demo)
    (root / "demo" / "__init__.py").unlink()
    s.judged(root, demo)
    result = verdict(tmp_path, demo, submission=s.submission(changed_files=["demo/__init__.py", "demo/core.py", "setup.py"]))
    assert failed(result) == ["allowed_files_only"] and "demo/__init__.py was deleted" in result["message"]


def test_limits(tmp_path: Path, demo: dict):
    files = dict(s.UPGRADED)
    files["demo/core.py"] += "".join(f"VALUE_{n} = {n}\n" for n in range(200))
    s.judged(upgraded(tmp_path, demo, files), demo)
    result = verdict(tmp_path, demo)
    assert failed(result) == ["within_limits"] and "added lines (at most 150)" in result["message"]


@pytest.mark.parametrize(
    ("setup_line", "message"),
    [
        ('install_requires=["httpx>=0.25.0", "six", "requests"]', "requirement added that is not allowed: requests"),
        ('install_requires=["httpx>=0.25.0"]', "requirement removed: six"),
        ('install_requires=["httpx>=0.25.0", "six>=1.16"]', "requirement changed that the upgrade does not need: six>=1.16"),
        ('install_requires=["httpx @ https://example.com/httpx.whl", "six"]', "points at a URL"),
        ('install_requires=["httpx>=0.25.0; python_version > \'3\'", "six"]', "must be required unconditionally"),
    ],
)
def test_the_spec_may_only_raise_the_dependency(tmp_path: Path, demo: dict, setup_line: str, message: str):
    files = dict(s.UPGRADED)
    files["setup.py"] = s.FILES["setup.py"].replace('install_requires=["httpx>=0.25.0,<0.28.0", "six"]', setup_line)
    s.judged(upgraded(tmp_path, demo, files), demo)
    result = verdict(tmp_path, demo)
    assert "spec_scope" in failed(result)
    assert message in by_id(result)["spec_scope"]["message"]


def test_the_rest_of_the_spec_file_stays(tmp_path: Path, demo: dict):
    files = dict(s.UPGRADED)
    files["setup.py"] = files["setup.py"].replace('name="demo"', 'name="demo2"')
    s.judged(upgraded(tmp_path, demo, files), demo)
    assert "the rest of the file changed too" in by_id(verdict(tmp_path, demo))["spec_scope"]["message"]


def test_the_requirement_must_admit_the_target(tmp_path: Path, demo: dict):
    files = dict(s.UPGRADED)
    files["setup.py"] = s.FILES["setup.py"].replace('"httpx>=0.25.0,<0.28.0"', '"httpx>=0.25.0,<0.28.1"')
    s.judged(upgraded(tmp_path, demo, files), demo)
    result = verdict(tmp_path, demo, submission=s.submission(requirement="httpx>=0.25.0,<0.28.1"))
    assert failed(result) == ["spec_admits_target"] and "does not admit 0.28.1" in result["message"]


def test_the_requirement_must_exclude_the_old_version_when_upstreams_did(tmp_path: Path, demo: dict):
    demo["spec"]["must_exclude_old"] = True
    (catalog.DATA / "catalog.json").write_text(json.dumps({"version": 1, "instances": [demo]}))
    catalog.load.cache_clear()
    s.judged(upgraded(tmp_path, demo), demo)
    result = verdict(tmp_path, demo)
    assert failed(result) == ["spec_admits_target"] and "still admits 0.27.2" in result["message"]


def test_the_lock_must_pin_the_target_with_pypis_hashes(tmp_path: Path, demo: dict):
    root = judged_wrongly(tmp_path, demo)
    text = s.lock("0.28.0")
    (root / ".judge" / "requirements.lock").write_text(text)
    judgement = json.loads((root / ".judge" / "judgement.json").read_text())
    judgement["lock"]["sha256"] = hashlib.sha256(text.encode()).hexdigest()
    (root / ".judge" / "judgement.json").write_text(json.dumps(judgement))
    result = verdict(tmp_path, demo)
    assert "lock_target" in failed(result) and "The lock holds httpx 0.28.0, not 0.28.1" in result["message"]


def test_hashes_that_are_not_pypis_fail(tmp_path: Path, demo: dict):
    judged_wrongly(tmp_path, demo)
    result = verdict(tmp_path, demo, pin=s.pin(demo, files=[("httpx-0.28.1-py3-none-any.whl", "e" * 64), ("httpx-0.28.1.tar.gz", "f" * 64)]))
    assert {"instance_pinned", "lock_target"} <= set(failed(result))


def test_a_lock_changed_after_judging_fails(tmp_path: Path, demo: dict):
    root = judged_wrongly(tmp_path, demo)
    (root / ".judge" / "requirements.lock").write_text(s.lock("0.27.2"))
    result = verdict(tmp_path, demo)
    assert failed(result) == ["lock_target"] and "The lock changed after judging" in result["message"]


def test_nothing_else_in_the_lock_may_move(tmp_path: Path, demo: dict):
    root = judged_wrongly(tmp_path, demo)
    text = s.lock(s.NEW).replace("anyio==4.7.0", "anyio==4.8.0")
    (root / ".judge" / "requirements.lock").write_text(text)
    judgement = json.loads((root / ".judge" / "judgement.json").read_text())
    judgement["lock"]["sha256"] = hashlib.sha256(text.encode()).hexdigest()
    (root / ".judge" / "judgement.json").write_text(json.dumps(judgement))
    result = verdict(tmp_path, demo)
    assert failed(result) == ["lock_scope"] and "anyio 4.7.0 -> 4.8.0" in result["message"]


@pytest.mark.parametrize("line", ["import warnings\nwarnings.filterwarnings('ignore')\n", "import sys\nTESTING = 'pytest' in sys.argv[0]\n"])
def test_shims_in_added_lines_fail(tmp_path: Path, demo: dict, line: str):
    files = dict(s.UPGRADED)
    files["demo/core.py"] = line + files["demo/core.py"]
    s.judged(upgraded(tmp_path, demo, files), demo)
    result = verdict(tmp_path, demo)
    assert failed(result) == ["no_shims"] and result["message"].startswith("1 of 19 checks failed. First: Shim at demo/core.py:")


def test_a_shim_already_in_the_pristine_code_is_not_the_agents(tmp_path: Path, demo: dict):
    files = dict(s.FILES)
    files["demo/core.py"] = "import sys\nARGS = sys.argv\n" + files["demo/core.py"]
    s.write_project(tmp_path / "project2", files)
    item = s.install_catalog(tmp_path / "data2", tmp_path / "project2")
    root = s.started_workspace(tmp_path / "ws", item, files=files)
    s.write_project(root, {"setup.py": s.UPGRADED["setup.py"]})
    s.judged(root, item)
    result = verdict(tmp_path / "ws", item, submission=s.submission(changed_files=["setup.py"]))
    assert by_id(result)["no_shims"]["ok"] is True


def test_a_never_started_project_is_not_checked(tmp_path: Path, demo: dict):
    result = verdict(tmp_path, demo)
    checks = by_id(result)
    assert checks["submission_matches"]["ok"] is None and "never set up" in checks["submission_matches"]["message"]
    assert result["valid"] is False


def test_an_altered_pristine_record_is_not_trusted(tmp_path: Path, demo: dict):
    root = judged_wrongly(tmp_path, demo)
    pristine = json.loads((root / ".judge" / "pristine.json").read_text())
    pristine["files"]["demo/core.py"] = "0" * 64
    (root / ".judge" / "pristine.json").write_text(json.dumps(pristine))
    checks = by_id(verdict(tmp_path, demo))
    assert checks["allowed_files_only"]["ok"] is None and "altered" in checks["allowed_files_only"]["message"]


def test_editable_paths(demo: dict):
    root = f"dep-upgrade/{s.ID}"
    assert editable_problem(f"{root}/demo/core.py") is None
    assert editable_problem(f"{root}/setup.py") is None
    assert editable_problem(f"{root}/demo/new_module.py") is None
    assert "may not change" in editable_problem(f"{root}/tests/test_core.py")
    assert "may not change" in editable_problem(f"{root}/README.md")
    assert "may not change" in editable_problem(f"{root}/demo/conftest.py")
    assert "reserved for the judge" in editable_problem(f"{root}/.judge/judgement.json")
    assert "inside the workspace" in editable_problem("../outside.py")


def test_edit_input_checks(demo: dict):
    good = EditInput(edits=[Edit(path=f"dep-upgrade/{s.ID}/demo/core.py", old="a", new="b")], then=Then.NOTHING)
    assert verifier.verify_input("edit_file", good)["valid"] is True
    bad = EditInput(edits=[Edit(path=f"dep-upgrade/{s.ID}/tests/test_core.py", old="a", new="b")], then=Then.NOTHING)
    assert verifier.verify_input("edit_file", bad)["valid"] is False
    empty = EditInput(edits=[Edit(path=f"dep-upgrade/{s.ID}/demo/core.py", old="", new="b")], then=Then.NOTHING)
    assert verifier.verify_input("edit_file", empty)["valid"] is False


def test_judge_output_must_agree_with_its_record(tmp_path: Path, demo: dict):
    root = judged_wrongly(tmp_path, demo)
    assert root.is_dir()
    given = UpgradeInput(instance=InstanceId(s.ID))
    made = JudgeOutput(recorded=True, complete=True, next="", changed_files=["demo/core.py", "setup.py"], requirement="httpx>=0.25.0", locked_version=s.NEW, installed_version=s.NEW, build_ok=True, public_passed=1, public_failed=0, violations=[], seconds=1.0)
    assert verifier.verify_output("judge", given, made, str(tmp_path))["valid"] is True
    wrong = JudgeOutput(**{**made.__dict__, "changed_files": ["setup.py"]})
    assert verifier.verify_output("judge", given, wrong, str(tmp_path))["valid"] is False
