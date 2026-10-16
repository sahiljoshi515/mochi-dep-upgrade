"""The judge's import probe (review F2), run here with this interpreter on small packages in a temp
folder: a project that changes the warnings filters or the dependency when imported is caught however
the code is spelled, and a clean one is not."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from plugin.probe import probe_tree, project_modules

DEPENDENCY = {"fakedep/__init__.py": "from fakedep.core import Client\n\n\ndef helper():\n    return 1\n", "fakedep/core.py": "class Client:\n    def get(self):\n        return 'GET'\n"}
ENTRY = {"id": "probe-demo", "source_globs": ["proj/**/*.py"], "path_entries": ["."], "import_names": ["fakedep"]}
# Names spelled through bytes, so that reading the code alone sees nothing.
FILTER = (
    "_n = bytes([115, 105, 109, 112, 108, 101, 102, 105, 108, 116, 101, 114]).decode()\n"
    "_k = bytes([99, 97, 116, 99, 104, 95, 119, 97, 114, 110, 105, 110, 103, 115]).decode()\n"
    "getattr([c for c in object.__subclasses__() if c.__name__ == _k][0]()._module, _n)('ignore')\n"
)


def probe(tmp_path: Path, project: dict[str, str]) -> dict:
    """The probe of a project tree, with the dependency installed outside it (as in site-packages)."""
    tree, site = tmp_path / "tree", tmp_path / "site"
    for folder, files in ((site, DEPENDENCY), (tree, project)):
        for rel, text in files.items():
            (folder / rel).parent.mkdir(parents=True, exist_ok=True)
            (folder / rel).write_text(text, encoding="utf-8")
    changed = [{"path": rel, "status": "modified"} for rel in project]
    env = {"PYTHONPATH": f"{tree}:{site}", "PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    return probe_tree(tree, ENTRY, changed, python=sys.executable, env=env, rundir=tmp_path / "probe", timeout=lambda: 60.0)


def test_the_modules_to_import():
    entry = {"source_globs": ["src/emcee/*.py", "src/emcee/moves/*.py"], "path_entries": ["src"]}
    changed = [{"path": "src/emcee/moves/de.py", "status": "modified"}, {"path": "src/emcee/old.py", "status": "deleted"}]
    assert project_modules(entry, changed) == (["emcee"], ["emcee", "emcee.moves.de"])


def test_a_clean_project_has_no_findings(tmp_path: Path):
    found = probe(tmp_path, {"proj/__init__.py": "import fakedep\n\n\ndef answer():\n    return fakedep.Client().get()\n"})
    assert found["ran"] is True and found["findings"] == [] and found["imported"] == ["proj"]


@pytest.mark.parametrize(
    ("code", "finding"),
    [
        (FILTER, "adds the warning filter ignore::builtins.Warning::0"),
        ("import warnings\nwarnings.showwarning = lambda *a, **k: None\n", "changes warnings.showwarning"),
        ("import fakedep\n\n\ndef helper():\n    return 2\n\n\nfakedep.helper = helper\n", "replaces fakedep.helper"),
        ("import fakedep\n\n\nclass Legacy:\n    pass\n\n\nfakedep.LegacyClient = Legacy\n", "adds fakedep.LegacyClient"),
        ("import fakedep.core\n\n\ndef get(self):\n    return 'POST'\n\n\nfakedep.core.Client.get = get\n", "puts the project's function proj.get [project] into fakedep.core.Client.get"),
        ("import fakedep\n\ndel fakedep.helper\n", "removes fakedep.helper"),
        ("raise SystemExit('not under the probe')\n", "leaves proj unimportable on its own"),
    ],
)
def test_what_the_import_does_is_found(tmp_path: Path, code: str, finding: str):
    found = probe(tmp_path, {"proj/__init__.py": code})
    assert any(item.startswith(finding) for item in found["findings"]), found["findings"]
