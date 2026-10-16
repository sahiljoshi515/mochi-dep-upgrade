"""The lock reader, the tree helpers and the glob matcher the verifier and the tools share."""

from __future__ import annotations

from pathlib import Path

import pytest

from verifier.locks import read_lock, versions_of
from verifier.trees import added_lines, changes, glob_regex, matches_any, tree_entries, tree_hash

LOCK = (
    "anyio==4.7.0 \\\n    --hash=sha256:" + "1" * 64 + " \\\n    --hash=sha256:" + "2" * 64 + "\n"
    "cffi==1.17.1 ; implementation_name != 'pypy' and os_name == 'nt' \\\n    --hash=sha256:" + "3" * 64 + "\n"
    "numpy==2.0.2 ; python_full_version < '3.10' \\\n    --hash=sha256:" + "4" * 64 + "\n"
    "numpy==2.2.1 ; python_full_version >= '3.10' \\\n    --hash=sha256:" + "5" * 64 + "\n"
)


def test_read_lock():
    packages = read_lock(LOCK)
    assert packages["anyio"][0]["hashes"] == ["1" * 64, "2" * 64]
    assert packages["cffi"][0]["marker"] == "implementation_name != 'pypy' and os_name == 'nt'"
    assert versions_of(packages)["numpy"] == ["2.0.2", "2.2.1"]


@pytest.mark.parametrize("text", ["anyio>=4.7 \\\n    --hash=sha256:" + "1" * 64 + "\n", "anyio==4.7.0\n", "anyio==4.7.0 \\\n    --index-url https://x\n", "-e .\n"])
def test_read_lock_refuses_what_is_not_a_hashed_pin(text: str):
    with pytest.raises(ValueError):
        read_lock(text)


def test_globs():
    assert glob_regex("respx/**/*.py").fullmatch("respx/mocks.py")
    assert glob_regex("respx/**/*.py").fullmatch("respx/sub/deep/x.py")
    assert not glob_regex("respx/*.py").fullmatch("respx/sub/x.py")
    assert not glob_regex("src/pkg/**/*.py").fullmatch("src/pkg/x.pyi")
    assert matches_any("setup.py", ["setup.py", "pkg/*.py"]) and not matches_any("setup.cfg", ["setup.py"])
    assert not glob_regex("a?.py").fullmatch("a/.py")


def test_changes_and_added_lines(tmp_path: Path):
    (tmp_path / "a.py").write_text("x = 1\ny = 2\n")
    (tmp_path / "b.py").write_text("keep\n")
    manifest = dict(tree_entries(tmp_path))
    (tmp_path / "a.py").write_text("x = 1\ny = 3\nz = 4\n")
    (tmp_path / "c.py").write_text("new\n")
    (tmp_path / "b.py").unlink()
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "a.cpython-312.pyc").write_bytes(b"\0")
    found = {item["path"]: item["status"] for item in changes(manifest, tree_entries(tmp_path))}
    assert found == {"a.py": "modified", "b.py": "deleted", "c.py": "added"}
    assert added_lines(["x = 1", "y = 2"], ["x = 1", "y = 3", "z = 4"]) == ["y = 3", "z = 4"]
    assert tree_hash([("a", "1"), ("b", "2")]) == tree_hash([("b", "2"), ("a", "1")])
