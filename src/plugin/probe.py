"""The judge's import probe: what importing the project does to the warnings filters, the warnings
module, the import hooks and the dependency's modules and classes, measured against a fresh interpreter
that loads the same third-party modules without the project (``runners/import_probe.py`` does both
runs). Reading the code (``verifier.shims``) cannot follow every spelling of a shim; running the import
shows its effect. What upstream's own tree does on import (ffn attaches its functions to pandas, for
one) is the instance's ``probe_expected``; anything else is a finding, and the verifier fails no-shims
on it.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

from plugin.common import Budget, run, scrub
from plugin.envs import venv_python
from plugin.testing import copy_tree, suite_env

RUNNER = Path(__file__).with_name("runners") / "import_probe.py"
PROBE_TIMEOUT = 60.0
MAX_FINDINGS = 200


def _module_name(rel: str, path_entries: list[str]) -> str | None:
    """``src/emcee/moves/de.py`` -> ``emcee.moves.de`` under the path entry ``src``; None outside them."""
    for entry_path in sorted(path_entries, key=len, reverse=True):
        prefix = "" if entry_path in (".", "") else entry_path.rstrip("/") + "/"
        if not rel.startswith(prefix) or not rel.endswith(".py"):
            continue
        parts = rel[len(prefix) : -3].split("/")
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts and all(part.isidentifier() for part in parts):
            return ".".join(parts)
    return None


def project_modules(entry: dict, changed: list[dict]) -> tuple[list[str], list[str]]:
    """``(packages, modules)``: the project's top-level packages (from its source globs), and what to
    import: those packages, then every changed module."""
    paths = entry.get("path_entries", ["."])
    packages: list[str] = []
    for glob in entry["source_globs"]:
        name = _module_name(glob.replace("**/", "").replace("*", "__init__"), paths)
        top = name.split(".")[0] if name else None
        if top and top not in packages:
            packages.append(top)
    modules = list(packages)
    for item in changed:
        if item["status"] == "deleted":
            continue
        name = _module_name(item["path"], paths)
        if name and name not in modules:
            modules.append(name)
    return packages, modules


def probe_tree(tree: Path, entry: dict, changed: list[dict], *, python: str, env: dict[str, str], rundir: Path, timeout: Callable[[], float]) -> dict:
    """Both runs of the probe on ``tree`` (a scratch copy) with ``python``; ``timeout()`` gives each run
    its time. Returns ``{"ran", "findings", "imported", "errors", "seconds"}`` (every finding, sorted),
    or ``{"timed_out": True}``."""
    packages, modules = project_modules(entry, changed)
    rundir = rundir.resolve()
    if rundir.exists():
        shutil.rmtree(rundir)
    rundir.mkdir(parents=True)
    shutil.copy(RUNNER, rundir / "import_probe.py")
    request = rundir / "request.json"
    roots = [str((tree / entry_path).resolve()) for entry_path in entry.get("path_entries", ["."])]
    request.write_text(json.dumps({"packages": packages, "modules": modules, "dependency": entry["import_names"], "roots": roots}), encoding="utf-8")
    script = str(rundir / "import_probe.py")
    seconds = 0.0
    first = run([python, "-B", "-s", script, "project", str(request), str(rundir / "project.json")], cwd=rundir, env=env, timeout=timeout())
    seconds += first.seconds
    if first.timed_out:
        return {"timed_out": True}
    second = None
    if (rundir / "project.json").is_file():
        second = run([python, "-B", "-s", script, "reference", str(request), str(rundir / "project.json"), str(rundir / "reference.json")], cwd=rundir, env=env, timeout=timeout())
        seconds += second.seconds
        if second.timed_out:
            return {"timed_out": True}
    result = rundir / "reference.json"
    if not result.is_file():
        tail = scrub((second or first).tail[-5:], tree, env=rundir)
        return {"ran": True, "findings": ["could not be probed: " + " ".join(tail)[-300:]], "imported": [], "errors": {}, "seconds": round(seconds, 2)}
    data = json.loads(result.read_text(encoding="utf-8"))
    errors = dict(data.get("errors", {}))
    findings = list(data.get("findings", []))
    # A package the tests import must import on its own too; one that does not may be hiding from the probe.
    findings += [f"leaves {name} unimportable on its own: {error}" for name, error in errors.items() if name in packages]
    return {"ran": True, "findings": sorted(set(findings))[:MAX_FINDINGS], "imported": data.get("imported", []), "errors": errors, "seconds": round(seconds, 2)}


def unexpected(entry: dict, findings: list[str]) -> list[str]:
    """The findings upstream's own tree does not have on import."""
    expected = set(entry.get("probe_expected", []))
    return [finding for finding in findings if finding not in expected]


def run_probe(root: Path, entry: dict, scratch: Path, changed: list[dict], budget: Budget) -> dict:
    """The judge's probe of the tree as it stands, in the judged environment; ``unexpected`` holds what
    upstream's tree does not do."""
    tree = copy_tree(root, scratch / "runs" / "probe-tree").resolve()
    found = probe_tree(tree, entry, changed, python=str(venv_python(scratch)), env=suite_env(tree, entry, scratch), rundir=scratch / "runs" / "probe", timeout=lambda: budget.slice(PROBE_TIMEOUT))
    if found.get("timed_out"):
        return found
    found["unexpected"] = unexpected(entry, found["findings"])[:30]
    found["ok"] = not found["unexpected"]
    return found
