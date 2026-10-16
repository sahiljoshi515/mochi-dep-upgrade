"""A small synthetic instance for offline tests: its own catalog (in a temp data folder the verifier
and the tools are pointed at), its locks, its project files, a workspace set up as start_upgrade
leaves it, and a judgement as judge records a correct upgrade. Each test then changes one thing."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from contract import InstanceId, PinOutput, PypiFile, UpgradeInput, UpgradeReportOutput
from verifier import catalog
from verifier.trees import tree_entries, tree_hash

ID = "respx-httpx-0.28"  # an id the contract's enum knows; the synthetic catalog gives it other content
DEP = "httpx"
OLD, NEW = "0.27.2", "0.28.1"
WHEEL_SHA = "a" * 64
SDIST_SHA = "b" * 64
FILES = {
    "README.md": "# demo\n",
    "setup.py": 'from setuptools import setup\n\nsetup(\n    name="demo",\n    install_requires=["httpx>=0.25.0,<0.28.0", "six"],\n)\n',
    "demo/__init__.py": "from demo.core import answer\n",
    "demo/core.py": "import httpx\n\n\ndef answer():\n    return httpx.Request('GET', 'https://x').method\n",
    "tests/test_core.py": "from demo import answer\n\n\ndef test_answer():\n    assert answer() == 'GET'\n",
}
UPGRADED = {
    "setup.py": FILES["setup.py"].replace('"httpx>=0.25.0,<0.28.0"', '"httpx>=0.25.0"'),
    "demo/core.py": "import httpx\n\n\ndef answer():\n    request = httpx.Request('GET', 'https://x')\n    return request.method\n",
}


def lock(version: str, *, extra: str = "") -> str:
    return (
        f"anyio==4.7.0 \\\n    --hash=sha256:{'1' * 64}\n"
        f"httpx=={version} \\\n    --hash=sha256:{WHEEL_SHA if version == NEW else 'c' * 64} \\\n    --hash=sha256:{SDIST_SHA if version == NEW else 'd' * 64}\n"
        f"six==1.16.0 \\\n    --hash=sha256:{'2' * 64}\n" + extra
    )


def entry(project: Path) -> dict:
    files = dict(tree_entries(project))
    return {
        "id": ID,
        "title": "demo: support httpx 0.28",
        "repo": "example/demo",
        "license": "MIT",
        "base": {"commit": "0" * 40, "tree_sha256": tree_hash(files.items()), "files": len(files), "bytes": 1},
        "upstream": {"commit": "1" * 40, "date": "2024-12-19T00:00:00Z", "message": "support httpx 0.28", "url": "https://github.com/example/demo/commit/" + "1" * 40},
        "dependency": DEP,
        "import_names": ["httpx"],
        "from_version": OLD,
        "target_version": NEW,
        "resolution_date": "2024-12-20T00:00:00Z",
        "python": "3.12",
        "spec": {"kind": "setup_py", "file": "setup.py", "base_requirement": "httpx>=0.25.0,<0.28.0", "upstream_requirement": "httpx>=0.25.0", "must_exclude_old": False},
        "source_globs": ["demo/**/*.py"],
        "test_dirs": ["tests"],
        "test_requirements": ["pytest"],
        "pytest_args": [],
        "path_entries": ["."],
        "env": {},
        "allowed_collateral": [],
        "allowed_new": [],
        "locks": {
            "base": "locks/demo.base.txt",
            "base_sha256": hashlib.sha256(lock(OLD).encode()).hexdigest(),
            "gold": "locks/demo.gold.txt",
            "gold_sha256": hashlib.sha256(lock(NEW).encode()).hexdigest(),
        },
        "target_files": [{"filename": "httpx-0.28.1-py3-none-any.whl", "sha256": WHEEL_SHA}, {"filename": "httpx-0.28.1.tar.gz", "sha256": SDIST_SHA}],
        "public": {"ids": ["tests/test_core.py::test_answer"], "excluded": []},
        "hidden": {"commit": "1" * 40, "files": {"tests/test_core.py": hashlib.sha256(FILES["tests/test_core.py"].encode()).hexdigest()}, "targets": ["tests/test_core.py"], "ids": ["tests/test_core.py::test_answer"]},
        "breaking": [{"test": "tests/test_core.py::test_answer", "error": "AttributeError"}],
        "limits": {"max_changed_files": 5, "max_new_files": 2, "max_added_lines": 150},
        "forbidden": [r"\bwarnings\.(?:filterwarnings|simplefilter|catch_warnings|resetwarnings)\b", r"\bsys\.argv\b"],
        "gold": {"files": ["demo/core.py", "setup.py"], "added_lines": 3},
        "fit": "hosted",
        "timings": {},
        "validated": {"platforms": ["test"], "at": "2026-10-16T00:00:00Z"},
        "notes": "",
    }


def install_catalog(data: Path, project: Path) -> dict:
    """Write the synthetic catalog and locks under ``data`` and point the verifier at them."""
    item = entry(project)
    (data / "locks").mkdir(parents=True, exist_ok=True)
    (data / "locks" / "demo.base.txt").write_text(lock(OLD), encoding="utf-8")
    (data / "locks" / "demo.gold.txt").write_text(lock(NEW), encoding="utf-8")
    (data / "catalog.json").write_text(json.dumps({"version": 1, "instances": [item]}), encoding="utf-8")
    catalog.DATA = data
    catalog.CATALOG = data / "catalog.json"
    catalog.load.cache_clear()
    return item


def write_project(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def started_workspace(workspace: Path, item: dict, *, run: str = "test-run", token: str = "token-1", files: dict[str, str] | None = None) -> Path:
    """The workspace as start_upgrade leaves it: the project, its pristine record and copies, the
    pre-upgrade lock and the ready record."""
    root = workspace / "dep-upgrade" / ID
    write_project(root, FILES if files is None else files)
    judge_dir = root / ".judge"
    files = dict(tree_entries(root))
    (judge_dir / "pristine").mkdir(parents=True, exist_ok=True)
    (judge_dir / "pristine.json").write_text(json.dumps({"instance": ID, "tree_sha256": tree_hash(files.items()), "files": files}), encoding="utf-8")
    for rel in ("setup.py", "demo/__init__.py", "demo/core.py"):
        copy = judge_dir / "pristine" / rel
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_bytes((root / rel).read_bytes())
    (judge_dir / "requirements.lock").write_text(lock(OLD), encoding="utf-8")
    (judge_dir / "ready.json").write_text(json.dumps({"run": run, "setup_token": token, "output": {}}), encoding="utf-8")
    return root


def judged(root: Path, item: dict, *, token: str = "token-1", **override) -> dict:
    """Write the judgement judge records for the tree as it stands (the upgrade done right) and the
    judged lock; ``override`` replaces top-level fields."""
    from verifier.shims import added_lines_by_file, pristine_manifest
    from verifier.trees import changes

    manifest = pristine_manifest(root)
    entries = tree_entries(root)
    changed = changes(manifest["files"], entries)
    added = added_lines_by_file(root, changed)
    text = lock(NEW)
    (root / ".judge" / "requirements.lock").write_text(text, encoding="utf-8")
    judgement = {
        "version": 2,
        "complete": True,
        "instance": ID,
        "catalog_sha256": catalog.entry_sha256(item),
        "setup_token": token,
        "base_tree_sha256": item["base"]["tree_sha256"],
        "target_version": NEW,
        "tree_sha256": tree_hash(entries),
        "tree_stable": True,
        "changed_files": [{**change, "added_lines": len(added.get(change["path"], []))} for change in changed],
        "spec": {"ok": True, "requirements": ["httpx>=0.25.0", "six"], "requirement": "httpx>=0.25.0"},
        "lock": {"ok": True, "sha256": hashlib.sha256(text.encode()).hexdigest(), "dependency_version": NEW},
        "install": {"ok": True, "installed": {"httpx": NEW, "anyio": "4.7.0", "six": "1.16.0"}, "pip_check": {"ok": True, "tail": []}},
        "build": {"ok": True, "wheel": "demo-1.0-py3-none-any.whl", "requires_dist": ["httpx>=0.25.0", "six"], "seconds": 1.0, "tail": []},
        "public": {"ran": True, "ok": True, "ids_sha256": catalog.ids_sha256(item["public"]["ids"]), "passed": 1, "failed": [], "failed_count": 0, "missing": [], "missing_count": 0},
        "hidden": {"ran": True, "ok": True, "ids_sha256": catalog.ids_sha256(item["hidden"]["ids"]), "passed": 1, "failed": [], "failed_count": 0, "missing": [], "missing_count": 0, "files_digest": catalog.hidden_digest(item["hidden"]["files"])},
        "forbidden": [],
        "seconds": 1.0,
        "judged_at": "2026-10-16T00:00:00Z",
    }
    judgement.update(override)
    (root / ".judge" / "judgement.json").write_text(json.dumps(judgement, indent=1, sort_keys=True), encoding="utf-8")
    return judgement


def pin(item: dict, *, prior: str = "", files: list[tuple[str, str]] | None = None) -> PinOutput:
    served = files if files is not None else [(f["filename"], f["sha256"]) for f in item["target_files"]]
    return PinOutput(
        instance=InstanceId(ID),
        catalog_sha256=catalog.entry_sha256(item),
        dependency=DEP,
        from_version=OLD,
        target_version=NEW,
        pypi_files=[PypiFile(filename=name, sha256=sha) for name, sha in served],
        pypi_yanked=False,
        prior_judgement_sha256=prior,
    )


def submission(**override) -> UpgradeReportOutput:
    values = {
        "instance": InstanceId(ID),
        "dependency": DEP,
        "from_version": OLD,
        "to_version": NEW,
        "requirement": "httpx>=0.25.0",
        "changed_files": ["demo/core.py", "setup.py"],
        "migration": ["Raised httpx to admit 0.28.1 in setup.py", "Read the request's method through a local in demo/core.py"],
    }
    values.update(override)
    return UpgradeReportOutput(**values)


def arguments() -> UpgradeInput:
    return UpgradeInput(instance=InstanceId(ID))
