"""A synthetic upgraded project in a workspace, with a judgement the trusted judge would have
written, and its pin: what verify_task reads. No uv, git or venv needed."""

from __future__ import annotations

import json
from pathlib import Path

from plugin.common import is_protected, sha256_bytes, tree_entries, tree_hash
from verifier.pyproject import blank_dependencies

PROJECT = "invoicer-pydantic-2"
PACKAGE = "invoicer"
DEPENDENCY = "pydantic"
FROM_VERSION = "1.10.13"
TARGET = "2.14.1"
HIDDEN_IDS = ["test_hidden_api.py::test_dump", "test_hidden_api.py::test_errors"]
FORBIDDEN = [
    r"pydantic\.v1",
    r"warnings\.(filterwarnings|simplefilter)",
    r"sys\.modules\[",
    r"^\s*pydantic(\.\w+)+\s*=[^=]",
    r"\b(import|from)\s+_?pytest\b",
]

PYPROJECT = """[build-system]
requires = ["hatchling>=1.25"]
build-backend = "hatchling.build"

[project]
name = "invoicer"
version = "1.4.0"
requires-python = ">=3.12"
dependencies = [
    {deps}
]

[dependency-groups]
dev = [
    "pytest>=8",
]
"""
PRISTINE_DEPS = '"pydantic>=1.10.13,<2",'
UPGRADED_DEPS = '"pydantic==2.14.1",\n    "pydantic-settings>=2.10",'

LOCK = """version = 1
requires-python = ">=3.12"

[[package]]
name = "invoicer"
version = "1.4.0"
source = {{ editable = "." }}

[[package]]
name = "pydantic"
version = "{pydantic}"
source = {{ {pydantic_source} }}

[[package]]
name = "pytest"
version = "{pytest}"
source = {{ registry = "https://pypi.org/simple" }}
{extra}"""
PYPI = 'registry = "https://pypi.org/simple"'
SETTINGS_PACKAGE = """
[[package]]
name = "pydantic-settings"
version = "2.15.0"
source = { registry = "https://pypi.org/simple" }
"""

PRISTINE_MODELS = "from pydantic import BaseModel, Field\n\n\nclass Invoice(BaseModel):\n    number: str = Field(..., regex='^INV')\n"
UPGRADED_MODELS = "from pydantic import BaseModel, Field\n\n\nclass Invoice(BaseModel):\n    number: str = Field(..., pattern='^INV')\n"
TESTS = "from invoicer.models import Invoice\n\n\ndef test_number():\n    assert Invoice(number='INV-1').number == 'INV-1'\n"
README = "# invoicer\n\nInvoices.\n"


def pristine_files() -> dict[str, str]:
    return {
        "pyproject.toml": PYPROJECT.format(deps=PRISTINE_DEPS),
        "uv.lock": LOCK.format(pydantic=FROM_VERSION, pydantic_source=PYPI, pytest="9.1.1", extra=""),
        "README.md": README,
        "tests/test_models.py": TESTS,
        f"src/{PACKAGE}/__init__.py": "",
        f"src/{PACKAGE}/models.py": PRISTINE_MODELS,
    }


def upgraded_files() -> dict[str, str]:
    files = pristine_files()
    files["pyproject.toml"] = PYPROJECT.format(deps=UPGRADED_DEPS)
    files["uv.lock"] = LOCK.format(pydantic=TARGET, pydantic_source=PYPI, pytest="9.1.1", extra=SETTINGS_PACKAGE)
    files[f"src/{PACKAGE}/models.py"] = UPGRADED_MODELS
    files[f"src/{PACKAGE}/settings.py"] = "from pydantic_settings import BaseSettings\n\n\nclass Settings(BaseSettings):\n    tax: float = 0.1\n"
    return files


def write_tree(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def pin_for(tmp_path: Path, *, hidden_ids=None, forbidden=None, **overrides) -> dict:
    """The pin_project output for the pristine synthetic project, as a plain dict."""
    pristine = tmp_path / "pristine"
    if not pristine.exists():
        write_tree(pristine, pristine_files())
    entries = tree_entries(pristine)
    pyproject = pristine_files()["pyproject.toml"]
    pin = {
        "project": PROJECT,
        "dependency": DEPENDENCY,
        "package": PACKAGE,
        "from_spec": "pydantic>=1.10.13,<2",
        "from_version": FROM_VERSION,
        "target_version": TARGET,
        "requires_python": ">=3.12",
        "pristine_tree_sha256": tree_hash(entries),
        "protected_tree_sha256": tree_hash(entry for entry in entries if is_protected(entry[0])),
        "pyproject_sha256": sha256_bytes(pyproject.encode()),
        "pyproject_rest_sha256": sha256_bytes(blank_dependencies(pyproject).encode()),
        "pristine_dependencies": ["pydantic>=1.10.13,<2"],
        "other_dependencies": {"pytest": "9.1.1"},
        "allowed_new_dependencies": ["pydantic-settings"],
        "allowed_collateral": [],
        "forbidden_patterns": FORBIDDEN if forbidden is None else forbidden,
        "hidden_tests_sha256": "a" * 64,
        "hidden_test_ids": HIDDEN_IDS if hidden_ids is None else hidden_ids,
        "max_new_files": 5,
        "max_added_lines": 600,
    }
    pin.update(overrides)
    return pin


def record_of(ids, *, failed=(), exit_status=None, collection_errors=None) -> dict:
    outcomes = {test: ("failed" if test in failed else "passed") for test in ids}
    status = (1 if failed or collection_errors else 0) if exit_status is None else exit_status
    return {
        "ok": status == 0 and not failed and not collection_errors,
        "command": "pytest",
        "exit_status": status,
        "collected": list(ids),
        "outcomes": outcomes,
        "messages": {test: "AssertionError" for test in failed},
        "collection_errors": dict(collection_errors or {}),
        "tail": [],
        "seconds": 0.5,
    }


def judge_workspace(root: Path, pin: dict, *, changed_override=None, **overrides) -> dict:
    """What the judge writes for the project at ``root`` when every outcome is good; the judgement
    is derived from the files as the judge derives it, so a mutated tree gets a consistent record
    unless a test overrides a field."""
    pristine = pristine_files()
    entries = tree_entries(root)
    current = dict(entries)
    changed = []
    for rel in sorted(set(current) | set(pristine)):
        if rel in pristine and rel in current:
            if sha256_bytes(pristine[rel].encode()) != current[rel]:
                added = max(0, len((root / rel).read_text().splitlines()) - len(pristine[rel].splitlines()))
                changed.append({"path": rel, "status": "modified", "sha256": current[rel], "added_lines": added})
        elif rel in current:
            changed.append({"path": rel, "status": "added", "sha256": current[rel], "added_lines": len((root / rel).read_text().splitlines())})
        else:
            changed.append({"path": rel, "status": "deleted", "sha256": "", "added_lines": 0})
    judgement = {
        "version": 1,
        "complete": True,
        "project": PROJECT,
        "dependency": DEPENDENCY,
        "target_version": TARGET,
        "package": PACKAGE,
        "pristine_tree_sha256": pin["pristine_tree_sha256"],
        "hidden_tests_sha256": pin["hidden_tests_sha256"],
        "protected_tree_sha256": tree_hash(entry for entry in entries if is_protected(entry[0])),
        "tree_sha256": tree_hash(entries),
        "tree_stable": True,
        "pyproject_sha256": current.get("pyproject.toml", ""),
        "uv_lock_sha256": current.get("uv.lock", ""),
        "changed_files": changed if changed_override is None else changed_override,
        "installed": {DEPENDENCY: TARGET, "pytest": "9.1.1"},
        "lock_check": {"ok": True, "tail": []},
        "build": {"ok": True, "wheel": "invoicer-1.4.0-py3-none-any.whl", "tail": [], "seconds": 2.0},
        "public": record_of(["tests/test_models.py::test_number"]),
        "hidden": record_of(pin["hidden_test_ids"]),
        "forbidden": [],
        "seconds": 10.0,
    }
    judgement.update(overrides)
    return judgement


def write_judgement(root: Path, judgement: dict) -> None:
    (root / ".judge").mkdir(exist_ok=True)
    (root / ".judge" / "judgement.json").write_text(json.dumps(judgement, indent=1), encoding="utf-8")


def gold_workspace(tmp_path: Path) -> tuple[Path, Path, dict]:
    """``(workspace, project root, pin)`` for a finished, correct upgrade."""
    workspace = tmp_path / "workspace"
    root = workspace / "dep-upgrade" / PROJECT
    write_tree(root, upgraded_files())
    pin = pin_for(tmp_path)
    write_judgement(root, judge_workspace(root, pin))
    return workspace, root, pin
