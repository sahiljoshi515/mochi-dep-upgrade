"""The tools that change the project, on the synthetic instance (no network): exact replacements,
all or none, only where the instance allows, with valid content; whole-file writes alike."""

from __future__ import annotations

from pathlib import Path

import pytest
import synthetic as s

from contract import (
    Edit,
    EditInput,
    FileWrite,
    InstanceId,
    ListInput,
    ReadInput,
    SearchInput,
    Then,
    UpgradeInput,
    WriteInput,
)
from contract import TestsInput as RunTestsInput
from plugin import project
from plugin.common import ToolError
from plugin.files import edit_file, list_files, read_file, search, write_file
from plugin.sync import check_targets, sync
from verifier import catalog

ROOT = f"dep-upgrade/{s.ID}"


@pytest.fixture
def started(tmp_path: Path, demo: dict) -> Path:
    s.started_workspace(tmp_path, demo, run=project.RUN)
    return tmp_path


def edit(path: str, old: str, new: str) -> Edit:
    return Edit(path=f"{ROOT}/{path}", old=old, new=new)


def test_edit_applies_exact_replacements_in_order(started: Path):
    out = edit_file(EditInput(edits=[edit("demo/core.py", "return httpx", "request = httpx"), edit("demo/core.py", "request = httpx.Request('GET', 'https://x').method", "request = httpx.Request('GET', 'https://x')\n    return request.method")], then=Then.NOTHING), started)
    assert [item.replacements for item in out.edited] == [2] and out.sync is None and out.tests is None
    assert (started / ROOT / "demo" / "core.py").read_text() == s.UPGRADED["demo/core.py"]


def test_edit_is_all_or_none(started: Path):
    before = (started / ROOT / "demo" / "core.py").read_text()
    with pytest.raises(ToolError, match="occurs 0 times"):
        edit_file(EditInput(edits=[edit("demo/core.py", "import httpx", "import httpx as h"), edit("demo/core.py", "not there", "x")], then=Then.NOTHING), started)
    assert (started / ROOT / "demo" / "core.py").read_text() == before


@pytest.mark.parametrize(
    ("path", "old", "new", "message"),
    [
        ("tests/test_core.py", "GET", "POST", "may not change"),
        ("README.md", "demo", "x", "may not change"),
        ("demo/core.py", "def answer():", "def answer(:", "would not be valid Python"),
        ("demo/core.py", "\n", "\n\n", "occurs"),
        ("setup.py", 'name="demo"', 'name="other"', "only the requirements in setup.py may change"),
        (".judge/ready.json", "run", "x", "reserved for the judge"),
    ],
)
def test_edit_refusals(started: Path, path: str, old: str, new: str, message: str):
    with pytest.raises(ToolError, match=message):
        edit_file(EditInput(edits=[edit(path, old, new)], then=Then.NOTHING), started)


@pytest.mark.parametrize("name", ["sitecustomize.py", "usercustomize.py", "conftest.py"])
def test_files_the_interpreter_or_pytest_would_load_may_not_be_written(started: Path, name: str):
    # The tool and the input verifier share one predicate (review F3).
    with pytest.raises(ToolError, match="may not change"):
        write_file(WriteInput(files=[FileWrite(path=f"{ROOT}/demo/{name}", content="x = 1\n")], then=Then.NOTHING), started)


@pytest.mark.parametrize(("requirement", "message"), [('"httpx~=0"', "~= needs at least two release segments"), ('"httpx>=0.28+local"', "cannot take a local version")])
def test_an_invalid_specifier_is_refused_where_it_is_written(started: Path, requirement: str, message: str):
    # Review F4: refused by edit_file with the reason, not left to fail later as a lock that does not resolve.
    with pytest.raises(ToolError, match=message):
        edit_file(EditInput(edits=[edit("setup.py", '"httpx>=0.25.0,<0.28.0"', requirement)], then=Then.NOTHING), started)


def test_the_spec_requirements_may_change(started: Path):
    edit_file(EditInput(edits=[edit("setup.py", '"httpx>=0.25.0,<0.28.0"', '"httpx>=0.25.0"')], then=Then.NOTHING), started)
    assert '"httpx>=0.25.0"' in (started / ROOT / "setup.py").read_text()


def test_edit_keeps_line_endings(started: Path):
    path = started / ROOT / "demo" / "core.py"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    edit_file(EditInput(edits=[edit("demo/core.py", "import httpx", "import httpx  # client")], then=Then.NOTHING), started)
    assert b"import httpx  # client\r\n" in path.read_bytes()


def test_write_creates_new_source_files_but_nothing_else(started: Path):
    out = write_file(WriteInput(files=[FileWrite(path=f"{ROOT}/demo/compat.py", content="VALUE = 1\n")], then=Then.NOTHING), started)
    assert out.written[0].bytes == 10
    with pytest.raises(ToolError, match="may not change"):
        write_file(WriteInput(files=[FileWrite(path=f"{ROOT}/tests/test_new.py", content="x = 1\n")], then=Then.NOTHING), started)
    with pytest.raises(ToolError, match="may not change"):
        write_file(WriteInput(files=[FileWrite(path=f"{ROOT}/demo/conftest.py", content="x = 1\n")], then=Then.NOTHING), started)


def test_tools_need_this_runs_start(tmp_path: Path, demo: dict):
    s.started_workspace(tmp_path, demo, run="an-earlier-run")
    with pytest.raises(ToolError, match="start_upgrade .* first"):
        edit_file(EditInput(edits=[edit("demo/core.py", "import httpx", "import httpx")], then=Then.NOTHING), tmp_path)
    with pytest.raises(ToolError, match="start_upgrade .* first"):
        sync(UpgradeInput(instance=InstanceId(s.ID)), tmp_path)


def test_reads_stay_out_of_the_judges_folder(started: Path):
    listed = list_files(ListInput(path=ROOT, max_entries=200), started)
    assert listed.entries and all(".judge" not in entry.path.split("/") for entry in listed.entries)
    with pytest.raises(ToolError, match="reserved for the judge"):
        read_file(ReadInput(path=f"{ROOT}/.judge/ready.json", start_line=1, max_lines=5), started)
    hits = search(SearchInput(path=ROOT, pattern="httpx", glob="*.py", max_hits=10), started)
    assert hits.hits and all(".judge" not in hit.path for hit in hits.hits)


def test_test_targets_stay_in_the_test_folders(demo: dict):
    entry = catalog.entry(s.ID)
    assert check_targets(entry, []) == ["tests"]
    assert check_targets(entry, ["tests/test_core.py::test_answer"]) == ["tests/test_core.py::test_answer"]
    for bad in ("demo/core.py", "-x", "../tests/x.py", "/abs/tests/x.py"):
        with pytest.raises(ToolError):
            check_targets(entry, [bad])
    assert RunTestsInput(instance=InstanceId(s.ID), tests=[]).tests == []
