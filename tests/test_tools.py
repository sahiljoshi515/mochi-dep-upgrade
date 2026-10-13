"""The tools' own rules, without uv or a network: confinement, listings, reads, searches, writes,
the forbidden-pattern scan, the pytest recorder and the pin of every shipped project."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from slimconfig import build_output, plain_output

from contract import (
    FileWrite,
    ListInput,
    PinOutput,
    ProjectId,
    ReadInput,
    SearchInput,
    UpgradeInput,
    WriteInput,
    Written,
)
from plugin.build import RUNNER, check_targets
from plugin.common import (
    PLUGIN_ROOT,
    Budget,
    ToolError,
    confine,
    is_protected,
    load_progress,
    save_progress,
    scrub,
    tree_entries,
    tree_hash,
)
from plugin.files import cap_lines, list_files, read_file, search, write_file
from plugin.instances import all_instances, load_instance
from plugin.judge import scan_forbidden
from plugin.project import READY, direct_dependency_names, locked_versions, pin_project, rules_for, uses_of
from plugin.tools_dev.patches import changed_files_of

PROJECT = "invoicer-pydantic-2"


def started_workspace(tmp_path: Path) -> tuple[Path, Path]:
    """A workspace with the pristine invoicer project copied in and marked ready (no venv)."""
    inst = load_instance(PROJECT)
    root = tmp_path / "dep-upgrade" / PROJECT
    import shutil

    shutil.copytree(inst.project_dir, root, ignore=shutil.ignore_patterns("__pycache__"))
    (root / ".judge").mkdir()
    (root / ".judge" / READY).write_text("{}")
    return tmp_path, root


def test_confine_rejects_escapes(tmp_path: Path):
    (tmp_path / "inside").mkdir()
    assert confine(tmp_path, "inside") == (tmp_path / "inside").resolve()
    for bad in ("/etc/passwd", "../x", "a/../../x", "", " ", "a\0b", ".judge/x", "dep-upgrade/p/.judge/judgement.json"):
        with pytest.raises(ToolError):
            confine(tmp_path, bad)
    assert confine(tmp_path, ".judge/x", allow_judge=True).name == "x"
    (tmp_path / "link").symlink_to("/etc")
    with pytest.raises(ToolError, match="inside the workspace"):
        confine(tmp_path, "link/passwd")


def test_listing_reading_and_searching(tmp_path: Path):
    workspace, root = started_workspace(tmp_path)
    (root / ".venv").mkdir()
    (root / ".venv" / "secret.py").write_text("x")
    listed = list_files(ListInput(path=f"dep-upgrade/{PROJECT}", max_entries=200), workspace)
    paths = [entry.path for entry in listed.entries]
    assert f"dep-upgrade/{PROJECT}/pyproject.toml" in paths and f"dep-upgrade/{PROJECT}/src/invoicer/models.py" in paths
    assert not any(".venv" in path or ".judge" in path for path in paths)
    assert listed.truncated is False and listed.total == len(paths)
    short = list_files(ListInput(path=f"dep-upgrade/{PROJECT}", max_entries=3), workspace)
    assert len(short.entries) == 3 and short.truncated is True and short.total == listed.total

    read = read_file(ReadInput(path=f"dep-upgrade/{PROJECT}/pyproject.toml", start_line=1, max_lines=5), workspace)
    assert read.lines[0] == "[build-system]" and len(read.lines) == 5 and read.total_lines > 5
    tail = read_file(ReadInput(path=f"dep-upgrade/{PROJECT}/pyproject.toml", start_line=read.total_lines, max_lines=50), workspace)
    assert len(tail.lines) == 1
    with pytest.raises(ToolError):
        read_file(ReadInput(path=f"dep-upgrade/{PROJECT}/src", start_line=1, max_lines=5), workspace)
    with pytest.raises(ToolError):
        read_file(ReadInput(path=f"dep-upgrade/{PROJECT}/.judge/ready.json", start_line=1, max_lines=5), workspace)

    found = search(SearchInput(path=f"dep-upgrade/{PROJECT}", pattern=r"regex=", glob="*.py", max_hits=50), workspace)
    assert found.hits and all(hit.path.startswith(f"dep-upgrade/{PROJECT}/src/") for hit in found.hits)
    assert all("regex=" in hit.text for hit in found.hits)
    capped = search(SearchInput(path=f"dep-upgrade/{PROJECT}", pattern=r"import", glob="*.py", max_hits=2), workspace)
    assert len(capped.hits) == 2 and capped.truncated is True
    with pytest.raises(ToolError, match="regular expression"):
        search(SearchInput(path=f"dep-upgrade/{PROJECT}", pattern="(", glob="*", max_hits=5), workspace)


def test_write_file_rules(tmp_path: Path):
    workspace, root = started_workspace(tmp_path)
    models = f"dep-upgrade/{PROJECT}/src/invoicer/models.py"
    made = write_file(WriteInput(files=[FileWrite(path=models, content="X = 1\n")]), workspace)
    assert made.written == [Written(path=models, bytes=6)] and (root / "src/invoicer/models.py").read_text() == "X = 1\n"
    new = f"dep-upgrade/{PROJECT}/src/invoicer/compat/__init__.py"
    both = write_file(WriteInput(files=[FileWrite(path=new, content=""), FileWrite(path=models, content="X = 2\n")]), workspace)
    assert [item.path for item in both.written] == [new, models] and (root / "src/invoicer/compat/__init__.py").is_file()
    for path in (
        f"dep-upgrade/{PROJECT}/tests/test_models.py",
        f"dep-upgrade/{PROJECT}/uv.lock",
        f"dep-upgrade/{PROJECT}/README.md",
        f"dep-upgrade/{PROJECT}/src/invoicer/notes.txt",
        f"dep-upgrade/{PROJECT}/src/other/x.py",
        f"dep-upgrade/{PROJECT}/src/invoicer/conftest.py",
        f"dep-upgrade/{PROJECT}/.judge/judgement.json",
        "dep-upgrade/ledger-sqlalchemy-2/pyproject.toml",
        "pyproject.toml",
    ):
        with pytest.raises(ToolError):
            write_file(WriteInput(files=[FileWrite(path=path, content="x = 1\n")]), workspace)
    # All or none: a refused file in the batch leaves the good one unwritten.
    with pytest.raises(ToolError, match="valid Python"):
        write_file(WriteInput(files=[FileWrite(path=models, content="X = 3\n"), FileWrite(path=models.replace("models", "broken"), content="def broken(:\n")]), workspace)
    assert (root / "src/invoicer/models.py").read_text() == "X = 2\n" and not (root / "src/invoicer/broken.py").exists()
    with pytest.raises(ToolError, match="limit"):
        write_file(WriteInput(files=[FileWrite(path=models, content="#" * (60 * 1024 + 1))]), workspace)
    with pytest.raises(ToolError, match="1 to 5"):
        write_file(WriteInput(files=[]), workspace)
    with pytest.raises(ToolError, match="twice"):
        write_file(WriteInput(files=[FileWrite(path=models, content="a = 1\n"), FileWrite(path=models, content="a = 2\n")]), workspace)

    pyproject = f"dep-upgrade/{PROJECT}/pyproject.toml"
    pristine = (load_instance(PROJECT).project_dir / "pyproject.toml").read_text()
    bumped = pristine.replace('"pydantic>=1.10.13,<2",', '"pydantic==2.14.1",\n    "pydantic-settings>=2.10",')
    assert write_file(WriteInput(files=[FileWrite(path=pyproject, content=bumped)]), workspace).written[0].bytes == len(bumped.encode())
    with pytest.raises(ToolError, match="dependencies array"):
        write_file(WriteInput(files=[FileWrite(path=pyproject, content=pristine.replace('requires-python = ">=3.12"', 'requires-python = ">=3.13"'))]), workspace)
    with pytest.raises(ToolError, match="dependencies array"):
        write_file(WriteInput(files=[FileWrite(path=pyproject, content=pristine + "\n[tool.ruff]\nline-length = 100\n")]), workspace)
    with pytest.raises(ToolError, match="TOML"):
        write_file(WriteInput(files=[FileWrite(path=pyproject, content="[project\n")]), workspace)
    with pytest.raises(ToolError, match="requirements"):
        write_file(WriteInput(files=[FileWrite(path=pyproject, content=pristine.replace('"pydantic>=1.10.13,<2",', '"pydantic >= one",'))]), workspace)


def test_read_file_stays_under_8_kb(tmp_path: Path):
    workspace, root = started_workspace(tmp_path)
    big = f"dep-upgrade/{PROJECT}/src/invoicer/big.py"
    (root / "src/invoicer/big.py").write_text("\n".join(f"line_{n} = {'x' * 100!r}" for n in range(200)) + "\n")
    read = read_file(ReadInput(path=big, start_line=1, max_lines=200), workspace)
    assert read.truncated is True and 0 < len(read.lines) < 200
    assert sum(len(line.encode()) + 1 for line in read.lines) <= 8 * 1024
    rest = read_file(ReadInput(path=big, start_line=1 + len(read.lines), max_lines=200), workspace)
    assert rest.start_line == 1 + len(read.lines)
    assert cap_lines(["x" * 9000]) == (["x" * 8191], True)
    assert cap_lines(["a", "b"]) == (["a", "b"], False)


def test_uses_of_lists_the_importing_modules(tmp_path: Path):
    _workspace, root = started_workspace(tmp_path)
    uses = uses_of(root, load_instance(PROJECT))
    assert "src/invoicer/models.py" in uses and "src/invoicer/settings.py" in uses
    assert "src/invoicer/errors.py" not in uses and len(uses) <= 20
    notes_root = tmp_path / "dep-upgrade" / "notes-flask-3"
    import shutil

    shutil.copytree(load_instance("notes-flask-3").project_dir, notes_root)
    assert "src/notes/slugs.py" in uses_of(notes_root, load_instance("notes-flask-3"))


def test_progress_and_budget(tmp_path: Path):
    assert load_progress(tmp_path) == {}
    save_progress(tmp_path, {"start": {"copied": True}})
    assert load_progress(tmp_path) == {"start": {"copied": True}}
    (tmp_path / ".judge" / "progress.json").write_text("not json")
    assert load_progress(tmp_path) == {}
    budget = Budget(seconds=100)
    assert budget.allows(50) and budget.slice(30) == 30 and budget.slice(200) <= 95
    spent = Budget(seconds=0)
    assert not spent.allows(1) and spent.slice(30) == 1.0


def test_write_file_needs_a_started_project(tmp_path: Path):
    with pytest.raises(ToolError, match="start_project"):
        write_file(WriteInput(files=[FileWrite(path=f"dep-upgrade/{PROJECT}/pyproject.toml", content="x")]), tmp_path)


def test_forbidden_scan_and_targets(tmp_path: Path):
    src = tmp_path / "src"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "a.py").write_text("import warnings\nwarnings.filterwarnings('ignore')\nfrom pydantic.v1 import BaseModel\n")
    (src / "pkg" / "b.py").write_text("x = 1\n")
    found = scan_forbidden(src, (r"pydantic\.v1", r"warnings\.(filterwarnings|simplefilter)"))
    assert found == ["src/pkg/a.py:2: warnings\\.(filterwarnings|simplefilter)", "src/pkg/a.py:3: pydantic\\.v1"]
    assert scan_forbidden(src, ()) == []

    root = tmp_path / "root"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_x.py").write_text("")
    assert check_targets(root, []) == ["tests"]
    assert check_targets(root, ["tests/test_x.py::test_a", "tests"]) == ["tests/test_x.py::test_a", "tests"]
    for bad in (["-k", "x"], ["src/x.py"], ["tests/missing.py"], ["../tests"], ["tests/x.py"] * 51):
        with pytest.raises(ToolError):
            check_targets(root, bad)


def test_pytest_recorder_records_every_outcome(tmp_path: Path):
    rundir = tmp_path / "run"
    rundir.mkdir()
    (rundir / "nanoagent_pytest_json.py").write_text(RUNNER.read_text())
    (rundir / "test_sample.py").write_text(
        "import pytest\n\n"
        "def test_ok():\n    assert True\n\n"
        "def test_bad():\n    assert 1 == 2\n\n"
        "@pytest.mark.skip\ndef test_skipped():\n    pass\n\n"
        "@pytest.mark.xfail\ndef test_xfail():\n    assert False\n\n"
        "@pytest.fixture\ndef broken():\n    raise RuntimeError('no')\n\n"
        "def test_error(broken):\n    pass\n"
    )
    (rundir / "test_broken.py").write_text("import nope\n")
    report = rundir / "report.json"
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "nanoagent_pytest_json", f"--nanoagent-json={report}", f"--rootdir={rundir}", "--continue-on-collection-errors", "test_sample.py", "test_broken.py"],
        cwd=rundir,
        env={**os.environ, "PYTHONPATH": str(rundir), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    data = json.loads(report.read_text())
    assert data["exit_status"] == completed.returncode != 0
    assert data["outcomes"] == {
        "test_sample.py::test_ok": "passed",
        "test_sample.py::test_bad": "failed",
        "test_sample.py::test_skipped": "skipped",
        "test_sample.py::test_xfail": "xfailed",
        "test_sample.py::test_error": "error",
    }
    assert data["collection_errors"] and "test_broken.py" in next(iter(data["collection_errors"]))
    assert "1 == 2" in data["messages"]["test_sample.py::test_bad"]


def test_scrub_hides_the_plugin_folder():
    assert scrub([f"at {PLUGIN_ROOT}/src/x.py", "fine"]) == ["at <plugin>/src/x.py", "fine"]


def test_tree_hash_rules(tmp_path: Path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "__pycache__").mkdir()
    (tmp_path / "tests" / "__pycache__" / "x.pyc").write_bytes(b"\0")
    (tmp_path / "tests" / "test_a.py").write_text("a")
    (tmp_path / ".judge").mkdir()
    (tmp_path / ".judge" / "judgement.json").write_text("{}")
    (tmp_path / "README.md").write_text("r")
    entries = tree_entries(tmp_path)
    assert [rel for rel, _ in entries] == ["README.md", "tests/test_a.py"]
    assert all(is_protected(rel) for rel, _ in entries)
    first = tree_hash(entries)
    (tmp_path / "tests" / "test_a.py").write_text("b")
    assert tree_hash(tree_entries(tmp_path)) != first


def test_pyproject_helpers():
    data = {"project": {"dependencies": ["Flask>=2.2,<2.3", "werkzeug>=2.2"]}, "dependency-groups": {"dev": ["pytest>=8", {"include-group": "x"}]}}
    assert direct_dependency_names(data) == ["flask", "werkzeug", "pytest"]
    lock = 'version = 1\n\n[[package]]\nname = "Flask"\nversion = "2.2.5"\n\n[[package]]\nname = "notes"\nversion = "2.3.1"\nsource = { editable = "." }\n'
    assert locked_versions(lock) == {"flask": "2.2.5", "notes": "2.3.1"}


@pytest.mark.parametrize("inst", all_instances(), ids=lambda inst: inst.id)
def test_every_shipped_project_pins_and_reads_back(tmp_path: Path, inst):
    pin = pin_project(UpgradeInput(project=ProjectId(inst.id)), tmp_path)
    assert build_output(plain_output(pin), PinOutput) == pin
    assert pin.from_version == inst.from_version and pin.target_version == inst.target_version
    assert pin.hidden_test_ids and all(test.startswith("test_hidden_") for test in pin.hidden_test_ids)
    assert pin.other_dependencies.get("pytest")
    assert inst.dependency.lower() not in pin.other_dependencies
    # The pristine code must use the breaking APIs the task is about; the hidden tests only the package.
    hidden_text = "\n".join(path.read_text() for path in inst.hidden_dir.glob("test_hidden_*.py"))
    assert f"import {inst.import_name}" not in hidden_text and f"from {inst.import_name}" not in hidden_text
    assert all("test_hidden_" in test for test in inst.hidden_test_ids)
    files = changed_files_of(inst)
    assert "pyproject.toml" in files and all(rel == "pyproject.toml" or rel.startswith(f"src/{inst.package}/") for rel in files)
    assert len(files) >= 2
    rules = rules_for(inst)
    assert any(inst.target_version in rule for rule in rules) and len(rules) >= 6
    assert not any(str(PLUGIN_ROOT) in rule for rule in rules)
    public_tests = sorted((inst.project_dir / "tests").glob("test_*.py"))
    assert public_tests and (inst.project_dir / "README.md").is_file() and (inst.project_dir / "uv.lock").is_file()
