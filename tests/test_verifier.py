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
    s.judged_lock(root, s.lock(s.NEW).replace("anyio==4.7.0", "anyio==4.8.0"))
    result = verdict(tmp_path, demo)
    assert failed(result) == ["lock_scope"]
    assert "anyio moved from 4.7.0 to 4.8.0; the upgrade keeps it at 4.7.0" in result["message"]


COLLATERAL_GOLD = s.lock(s.NEW).replace("anyio==4.7.0", "anyio==4.8.0") + f"sniffio==1.3.1 \\\n    --hash=sha256:{'3' * 64}\n"


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (lambda text: text, None),  # collateral and new packages stay where they were: the conservative upgrade
        (lambda text: text.replace("anyio==4.7.0", "anyio==4.8.0") + f"sniffio==1.3.1 \\\n    --hash=sha256:{'3' * 64}\n", None),  # where upstream's upgrade put them
        (lambda text: text.replace("anyio==4.7.0", "anyio==4.8.0"), None),  # collateral moved, the new package not brought in
        (lambda text: text.replace("anyio==4.7.0", "anyio==4.6.0"), "anyio is locked at 4.6.0; it may stay at 4.7.0 or move to 4.8.0, as upstream's upgrade did"),
        (lambda text: text + f"sniffio==1.3.0 \\\n    --hash=sha256:{'4' * 64}\n", "sniffio came into the lock at 1.3.0; the upgrade may bring it in at 1.3.1 only"),
        (lambda text: text.replace("six==1.16.0", "six==1.17.0"), "six moved from 1.16.0 to 1.17.0; the upgrade keeps it at 1.16.0"),
        (lambda text: text + f"requests==2.32.3 \\\n    --hash=sha256:{'5' * 64}\n", "requests 2.32.3 came into the lock; the upgrade brings in no requests"),
        (lambda text: text.replace(f"six==1.16.0 \\\n    --hash=sha256:{'2' * 64}\n", ""), "six is missing from the lock; the upgrade keeps it at 1.16.0"),
    ],
)
def test_collateral_may_stay_or_move_as_upstreams_did_and_nothing_else_moves(tmp_path: Path, demo: dict, change, problem):
    # Upstream's upgrade moved anyio (allowed collateral) and brought in sniffio (allowed new).
    s.set_locks(demo, gold=COLLATERAL_GOLD, allowed_collateral=["anyio"], allowed_new=["sniffio"])
    root = judged_wrongly(tmp_path, demo)
    s.judged_lock(root, change(s.lock(s.NEW)))
    result = verdict(tmp_path, demo)
    if problem is None:
        assert result["valid"] is True, result["message"]
    else:
        assert failed(result) == ["lock_scope"] and result["message"].endswith(problem)


def test_a_package_upstream_dropped_may_go_or_stay(tmp_path: Path, demo: dict):
    s.set_locks(demo, gold=s.lock(s.NEW).replace(f"six==1.16.0 \\\n    --hash=sha256:{'2' * 64}\n", ""))
    root = judged_wrongly(tmp_path, demo)
    assert verdict(tmp_path, demo)["valid"] is True
    s.judged_lock(root, s.lock(s.NEW).replace(f"six==1.16.0 \\\n    --hash=sha256:{'2' * 64}\n", ""))
    assert verdict(tmp_path, demo)["valid"] is True


# The challenger's evasions (review F2) and the other ways of spelling a shim; each line is added to
# demo/core.py, where httpx is the dependency.
SHIMS = {
    "getattr with a built name": "import warnings as _w\ngetattr(_w, 'filter'+'warnings')('ignore')\n",
    "the module's __dict__": "import warnings\nwarnings.__dict__['filterwarnings']('ignore')\n",
    "vars() of the module": "import warnings\nvars(warnings)['simple' 'filter']('ignore')\n",
    "an aliased sys.modules": "import sys as _s\n_s.modules['httpx_legacy'] = _s.modules['httpx']\n",
    "import_module with a built name": "import importlib\nimportlib.import_module('warn' + 'ings').simplefilter('ignore')\n",
    "a renamed from-import": "from warnings import simplefilter as _quiet\n_quiet('ignore')\n",
    "__import__": "__import__('warnings').filterwarnings('ignore')\n",
    "chr and join": "import warnings as w\ngetattr(w, ''.join([chr(115), 'implefilter']))('ignore')\n",
    "rot13": "import codecs, importlib\nimportlib.import_module(codecs.decode('jneavatf', 'rot13')).resetwarnings()\n",
    "a reversed string": "import importlib\nimportlib.import_module('sgninraw'[::-1]).simplefilter('ignore')\n",
    "emptying the filters": "import warnings\nwarnings.filters[:] = []\n",
    "exec": "exec('import warnings; warnings.simplefilter(\"ignore\")')\n",
    "reload": "import importlib\nimportlib.reload(httpx)\n",
    "setattr on the dependency": "setattr(httpx, 'BaseTransport', object)\n",
    "assigning into the dependency": "from httpx import Request as _R\n_R.method = property(lambda self: 'GET')\n",
    "writing the dependency's __dict__": "httpx.__dict__['URL'] = str\n",
    "the dependency's version": "OLD = httpx.__version__.startswith('0.27')\n",
    "a metadata lookup": "from importlib.metadata import version as _v\nOLD = _v('httpx') < '0.28'\n",
    "sys.argv": "import sys\nTESTING = 'pytest' in sys.argv[0]\n",
    "PYTEST_CURRENT_TEST": "import os\nTESTING = bool(os.environ.get('PYTEST_CURRENT_TEST'))\n",
    "globals()": "globals()['answer_old'] = None\n",
    "a warning emitted": "import warnings\nwarnings.warn('legacy')\n",
}


@pytest.mark.parametrize("name", sorted(SHIMS))
def test_shims_in_added_code_fail_however_spelled(tmp_path: Path, demo: dict, name: str):
    files = dict(s.UPGRADED)
    files["demo/core.py"] = files["demo/core.py"].replace("import httpx\n", "import httpx\n" + SHIMS[name], 1)
    s.judged(upgraded(tmp_path, demo, files), demo)
    result = verdict(tmp_path, demo)
    assert failed(result) == ["no_shims"] and result["message"].startswith("1 of 19 checks failed. First: Shim at demo/core.py:")


def test_a_rule_upstream_needs_is_exempt(tmp_path: Path, demo: dict):
    s.set_locks(demo, shim_exempt=["warnings"])
    files = dict(s.UPGRADED)
    files["demo/core.py"] = "import warnings\n" + files["demo/core.py"]
    s.judged(upgraded(tmp_path, demo, files), demo)
    assert verdict(tmp_path, demo)["valid"] is True


@pytest.mark.parametrize(
    ("probe", "message"),
    [
        ({"ran": True, "ok": False, "findings": ["adds the warning filter ignore::builtins.Warning::0"]}, "Importing the project adds the warning filter ignore::builtins.Warning::0"),
        ({"ran": True, "ok": False, "findings": ["replaces httpx.Request (function demo.core.Request [project], not class httpx._models.Request)"]}, "Importing the project replaces httpx.Request"),
        ({"ran": True, "ok": False, "findings": ["leaves demo unimportable on its own: RuntimeError: boom"]}, "Importing the project leaves demo unimportable"),
        ({"ran": False, "ok": False, "findings": []}, "The import probe did not run"),
        (None, "The judge did not run the import probe"),
    ],
)
def test_what_importing_the_project_does_is_checked(tmp_path: Path, demo: dict, probe, message: str):
    s.judged(upgraded(tmp_path, demo), demo, probe=probe)
    result = verdict(tmp_path, demo)
    assert failed(result) == ["no_shims"] and message in result["message"]


def test_what_upstreams_tree_does_on_import_is_expected(tmp_path: Path, demo: dict):
    finding = "puts the project's function demo.core.answer [project] into httpx.Client.answer"
    s.set_locks(demo, probe_expected=[finding])
    s.judged(upgraded(tmp_path, demo), demo, probe={"ran": True, "ok": True, "findings": [finding], "unexpected": []})
    assert verdict(tmp_path, demo)["valid"] is True


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
    # The tools' names (review F3): what pytest, the build or the interpreter would load as configuration.
    for name in ("sitecustomize.py", "usercustomize.py", "pytest.ini", "tox.ini", "setup.cfg"):
        assert "may not change" in editable_problem(f"{root}/demo/{name}")
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


def test_a_capitalised_distribution_name_is_looked_up_canonically(tmp_path: Path, demo: dict):
    demo["dependency"] = "HTTPX"
    (catalog.DATA / "catalog.json").write_text(json.dumps({"version": 1, "instances": [demo]}))
    catalog.load.cache_clear()
    s.judged(upgraded(tmp_path, demo), demo)
    result = verdict(tmp_path, demo, pin=s.pin(demo), submission=s.submission(dependency="HTTPX"))
    assert result["valid"] is True, result["message"]


@pytest.mark.parametrize("setup_line", ['"httpx~=0"', '"httpx>=0.28+local"'])
def test_an_invalid_specifier_is_the_first_reason_given(tmp_path: Path, demo: dict, setup_line: str):
    # Review F4: "~=" with one release segment (and a local label with >=) are not PEP 440; the
    # spec is written outside the tools, which refuse it.
    files = dict(s.UPGRADED)
    files["setup.py"] = s.FILES["setup.py"].replace('"httpx>=0.25.0,<0.28.0"', setup_line)
    root = upgraded(tmp_path, demo, files)
    s.judged(root, demo, spec={"ok": False, "requirements": [], "requirement": "", "error": "setup.py: not valid"}, lock={"ok": False, "tail": ["setup.py: not valid"]})
    result = verdict(tmp_path, demo, submission=s.submission(requirement=setup_line.strip('"')))
    first = next(item for item in result["details"]["constraints"] if item["ok"] is False)
    assert first["id"] == "submission_matches"
    assert ("~= needs at least two release segments" in first["message"]) or ("cannot take a local version" in first["message"])
    assert by_id(result)["spec_admits_target"]["message"] == first["message"]
