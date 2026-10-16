"""An instance's environment: its lock, computed from the spec, and the venv it is installed into.

A lock is ``uv pip compile --universal --generate-hashes --only-binary :all:`` of the spec's runtime
requirements plus the instance's test requirements, resolved as of the instance's resolution date
(``--exclude-newer``), with every package of the pre-upgrade lock held at its version by constraints
except the dependency and the packages the upgrade itself moves (its allowed collateral and new
packages). The venv lives in the launch's scratch folder and is rebuilt from the workspace's lock
when a later process finds it missing.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from plugin.common import Budget, Completed, ToolError, clean_env, run, sha256_bytes, uv
from plugin.pythons import python_for
from verifier import catalog
from verifier.locks import read_lock
from verifier.versions import canonical_name, parse_requirement

INDEX = "https://pypi.org/simple"
LOCK_TIMEOUT = 90.0
VENV_TIMEOUT = 60.0
INSTALL_TIMEOUT = 120.0
MARK = ".nanoagent-lock-sha256"


def env_for(scratch: Path, venv: Path | None = None) -> dict[str, str]:
    extra = {}
    if venv is not None:
        extra["VIRTUAL_ENV"] = str(venv)
    return clean_env(scratch / "home", extra=extra)


def requirements_in(entry: dict, runtime: list[str]) -> list[str]:
    """What a lock resolves: the spec's runtime requirements and the instance's test requirements."""
    return [*runtime, *entry.get("test_requirements", [])]


def constraints_for(entry: dict, *, released: set[str] | None = None) -> list[str]:
    """Every package of the pre-upgrade lock held at its version, except the dependency and the
    packages the upgrade may move (``released`` adds more names)."""
    free = {canonical_name(entry["dependency"])}
    free |= {canonical_name(name) for name in entry.get("allowed_collateral", [])}
    free |= {canonical_name(name) for name in entry.get("allowed_new", [])}
    free |= released or set()
    held = []
    for name, pins in read_lock(catalog.lock_text(entry, "base")).items():
        if name in free:
            continue
        for pin in pins:
            held.append(f"{name}=={pin['version']}" + (f" ; {pin['marker']}" if pin["marker"] else ""))
    return held


def compile_lock(entry: dict, runtime: list[str], scratch: Path, *, constraints: list[str] | None, timeout: float) -> tuple[Completed, str]:
    """``uv pip compile`` of ``runtime`` + the test requirements; returns the run and the lock text
    (empty when it failed)."""
    folder = scratch / "lock"
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    (folder / "requirements.in").write_text("".join(f"{line}\n" for line in requirements_in(entry, runtime)), encoding="utf-8")
    command = [
        uv(), "pip", "compile", "requirements.in",
        "--universal", "--python-version", entry["python"],
        "--generate-hashes", "--only-binary", ":all:",
        "--exclude-newer", entry["resolution_date"],
        "--index-url", INDEX,
        "--no-header", "--no-annotate", "--quiet",
        "--output-file", "requirements.lock",
    ]
    if constraints is not None:
        (folder / "constraints.txt").write_text("".join(f"{line}\n" for line in constraints), encoding="utf-8")
        command += ["--constraint", "constraints.txt"]
    done = run(command, cwd=folder, env=env_for(scratch), timeout=timeout)
    lock = folder / "requirements.lock"
    return done, (lock.read_text(encoding="utf-8") if done.ok and lock.is_file() else "")


def venv_dir(scratch: Path) -> Path:
    return scratch / "venv"


def venv_python(scratch: Path) -> Path:
    return venv_dir(scratch) / "bin" / "python"


def venv_minor(venv: Path) -> str:
    """The venv's Python minor version ("3.12"), from its pyvenv.cfg, or empty."""
    try:
        for line in (venv / "pyvenv.cfg").read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() in ("version", "version_info"):
                return ".".join(value.strip().split(".")[:2])
    except OSError:
        pass
    return ""


def ensure_venv(entry: dict, scratch: Path, lock_text: str, budget: Budget) -> str | None:
    """Make sure the scratch venv exists with exactly ``lock_text`` installed (wheels only, hashes
    required). Returns None when ready, or what to do when the budget ran out first."""
    venv = venv_dir(scratch)
    mark = venv / MARK
    wanted = sha256_bytes(lock_text.encode("utf-8"))
    if mark.is_file() and mark.read_text(encoding="utf-8").strip() == wanted:
        return None
    if (venv / "bin" / "python").exists() and venv_minor(venv) != entry["python"]:
        shutil.rmtree(venv, ignore_errors=True)
    if not (venv / "bin" / "python").exists():
        if not budget.allows(20):
            return "call again to create the project's environment"
        if venv.exists():
            shutil.rmtree(venv, ignore_errors=True)
        python = python_for(entry["python"], scratch)
        made = run([uv(), "venv", "-q", "--python", str(python), str(venv)], cwd=scratch, env=env_for(scratch), timeout=budget.slice(VENV_TIMEOUT))
        if made.timed_out:
            shutil.rmtree(venv, ignore_errors=True)
            return "call again to continue creating the project's environment"
        if not made.ok:
            raise ToolError("could not create the project's environment: " + " ".join(made.tail[-3:]))
    if not budget.allows(15):
        return "call again to install the project's environment"
    lock = scratch / "installed.lock"
    lock.write_text(lock_text, encoding="utf-8")
    installed = run(
        [uv(), "pip", "sync", "--require-hashes", "--only-binary", ":all:", "--exclude-newer", entry["resolution_date"], "--index-url", INDEX, "--python", str(venv / "bin" / "python"), str(lock)],
        cwd=scratch,
        env=env_for(scratch, venv),
        timeout=budget.slice(INSTALL_TIMEOUT),
    )
    if installed.timed_out:
        return "call again to continue installing the project's environment"
    if not installed.ok:
        raise ToolError("could not install the project's locked environment: " + " | ".join(installed.tail[-6:]))
    mark.write_text(wanted + "\n", encoding="utf-8")
    return None


def installed_versions(scratch: Path, names: list[str]) -> dict[str, str]:
    """Each distribution's version installed in the scratch venv, '' when it is missing (one short
    output line per name: output lines are cut to 200 characters)."""
    python = venv_python(scratch)
    if not python.exists():
        return {name: "" for name in names}
    script = (
        "import importlib.metadata as m, json, sys\n"
        "for name in json.loads(sys.argv[1]):\n"
        "    try:\n"
        "        print(name, m.version(name), sep='\\t')\n"
        "    except m.PackageNotFoundError:\n"
        "        print(name, '', sep='\\t')\n"
    )
    found = run([str(python), "-I", "-c", script, json.dumps(names)], cwd=scratch, env=env_for(scratch), timeout=30, tail=len(names) + 5)
    versions = {name: "" for name in names}
    if found.ok:
        for line in found.tail:
            name, _, version = line.partition("\t")
            if name in versions:
                versions[name] = version.strip()
    return versions


def pip_check(scratch: Path, budget: Budget) -> Completed:
    return run([uv(), "pip", "check", "--python", str(venv_python(scratch))], cwd=scratch, env=env_for(scratch), timeout=budget.slice(30), tail=20)


def dependency_requirement(entry: dict, requirements: list[str]) -> str:
    """The spec's requirement text for the instance's dependency, or empty."""
    wanted = canonical_name(entry["dependency"])
    for text in requirements:
        try:
            if parse_requirement(text).name == wanted:
                return text
        except ValueError:
            continue
    return ""


def lock_versions(lock_text: str) -> dict[str, list[str]]:
    return {name: sorted({pin["version"] for pin in pins}) for name, pins in read_lock(lock_text).items()}


def lock_changes(entry: dict, lock_text: str) -> list[str]:
    """``name old -> new`` for every package whose versions differ from the pre-upgrade lock."""
    before = lock_versions(catalog.lock_text(entry, "base"))
    after = lock_versions(lock_text)
    out = []
    for name in sorted(set(before) | set(after)):
        old, new = ",".join(before.get(name, [])) or "-", ",".join(after.get(name, [])) or "-"
        if old != new:
            out.append(f"{name} {old} -> {new}")
    return out
