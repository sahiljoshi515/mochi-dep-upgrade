"""The reference pin of a project, the project's environment outside the workspace, and setting a
project up in the workspace (resumably)."""

from __future__ import annotations

import dataclasses
import json
import re
import shutil
import sys
import tomllib
from pathlib import Path

from slimconfig import build_output, plain_output

from contract import PinOutput, StartOutput, UpgradeInput
from plugin.common import (
    JUDGE_DIR,
    TOOL_DIRS,
    Budget,
    ToolError,
    check_workspace_sizes,
    clean_env,
    is_protected,
    load_progress,
    project_root,
    prune_scratch,
    run,
    save_progress,
    scratch_home,
    sha256_bytes,
    tree_entries,
    tree_hash,
    uv,
)
from plugin.instances import Instance, load_instance
from verifier.pyproject import blank_dependencies, dependencies, requires_python
from verifier.versions import canonical_name, parse_requirement

READY = "ready.json"
INSTALLED_MARK = ".nanoagent-installed"
GIT_EXCLUDE = "\n".join([".venv/", JUDGE_DIR + "/", "__pycache__/", "*.pyc", ".pytest_cache/", "dist/", "build/", "*.egg-info/", ""])
MAX_LAYOUT = 40
MAX_USES = 20
VENV_TIMEOUT = 60.0
INSTALL_TIMEOUT = 130.0
# How a distribution is imported, when the name differs or the dash becomes an underscore.
IMPORT_NAMES = {"pydantic-settings": "pydantic_settings", "sqlalchemy": "sqlalchemy", "markupsafe": "markupsafe"}


def direct_dependency_names(data: dict) -> list[str]:
    """Every direct dependency of a pyproject: ``[project] dependencies``, its optional
    dependencies and every dependency group, canonical and without the project itself."""
    names: list[str] = []
    project = data.get("project", {})
    sources = [project.get("dependencies", [])]
    sources += list(project.get("optional-dependencies", {}).values())
    sources += list(data.get("dependency-groups", {}).values())
    for group in sources:
        for entry in group:
            if isinstance(entry, str):
                name = parse_requirement(entry).name
                if name not in names:
                    names.append(name)
    return names


def locked_versions(lock_text: str) -> dict[str, str]:
    data = tomllib.loads(lock_text)
    return {canonical_name(package["name"]): package.get("version", "") for package in data.get("package", [])}


def pin_project(given: UpgradeInput, workspace: Path) -> PinOutput:
    """What the verifier holds the task to: the pristine project's hashes, requirements and lock,
    the target, and the hidden tests' identity. Reads only the plugin's own copy."""
    inst = load_instance(given.project.value)
    project = inst.project_dir
    pyproject_text = (project / "pyproject.toml").read_text(encoding="utf-8")
    data = tomllib.loads(pyproject_text)
    written = dependencies(pyproject_text)
    if written != data["project"]["dependencies"]:
        raise ToolError("the pristine pyproject.toml dependencies do not read back the same way twice")
    python = requires_python(pyproject_text)
    if python != data["project"].get("requires-python", ""):
        raise ToolError("the pristine pyproject.toml requires-python does not read back")
    locked = locked_versions((project / "uv.lock").read_text(encoding="utf-8"))
    dependency = canonical_name(inst.dependency)
    if locked.get(dependency) != inst.from_version:
        raise ToolError(f"the pristine lock holds {inst.dependency} {locked.get(dependency)!r}, not {inst.from_version}")
    from_spec = next((entry for entry in written if parse_requirement(entry).name == dependency), None)
    if from_spec is None:
        raise ToolError(f"the pristine pyproject.toml does not require {inst.dependency}")
    others = {}
    for name in direct_dependency_names(data):
        if name == dependency:
            continue
        if name not in locked:
            raise ToolError(f"the pristine lock holds no version of {name}")
        others[name] = locked[name]
    entries = tree_entries(project)
    hidden = tree_entries(inst.hidden_dir)
    if not hidden:
        raise ToolError("the project has no hidden tests")
    return PinOutput(
        project=given.project,
        dependency=inst.dependency,
        package=inst.package,
        from_spec=from_spec,
        from_version=inst.from_version,
        target_version=inst.target_version,
        requires_python=python,
        pristine_tree_sha256=tree_hash(entries),
        protected_tree_sha256=tree_hash(entry for entry in entries if is_protected(entry[0])),
        pyproject_sha256=sha256_bytes(pyproject_text.encode("utf-8")),
        pyproject_rest_sha256=sha256_bytes(blank_dependencies(pyproject_text).encode("utf-8")),
        pristine_dependencies=list(written),
        other_dependencies=others,
        allowed_new_dependencies=list(inst.allowed_new_dependencies),
        allowed_collateral=list(inst.allowed_collateral),
        forbidden_patterns=list(inst.forbidden_patterns),
        hidden_tests_sha256=tree_hash(hidden),
        hidden_test_ids=list(inst.hidden_test_ids),
        max_new_files=inst.max_new_files,
        max_added_lines=inst.max_added_lines,
    )


def rules_for(inst: Instance) -> list[str]:
    collateral = ", ".join(inst.allowed_collateral) or "none"
    new = ", ".join(inst.allowed_new_dependencies) or "none"
    return [
        (
            f"Goal: {inst.dependency} {inst.from_version} -> exactly {inst.target_version}, with the project building and "
            "every test passing on the new version."
        ),
        (
            "You may change only the [project] dependencies array of pyproject.toml and .py files under "
            f"src/{inst.package}/ (at most {inst.max_new_files} new files, {inst.max_added_lines} added lines). "
            "tests/, README.md and uv.lock are read-only; sync rewrites uv.lock."
        ),
        (
            f"Raise {inst.dependency}'s requirement so that uv locks exactly {inst.target_version} (for example "
            f"{inst.dependency}=={inst.target_version}). Other requirements stay as written, except that these may change: "
            f"{collateral}. Requirements you may add: {new}. requires-python stays."
        ),
        (
            "No shims: no compatibility layers of the old API, no warning filters, no monkeypatching the library, no "
            "test-sniffing; migrate the code to the new API."
        ),
        "Tests run with warnings as errors: " + " ".join(inst.warning_flags) + ". Deprecated calls count as failures.",
        (
            "judge rebuilds the wheel, re-runs the public tests from a pristine copy and runs hidden tests that use the "
            "package the same way the public ones do, then records the result. Call it last, after sync; call it again "
            "if it returns complete: false."
        ),
        *inst.notes,
    ]


def ready_root(workspace: Path, project: str) -> tuple[Path, Instance]:
    inst = load_instance(project)
    root = project_root(workspace, inst.id)
    if not (root / JUDGE_DIR / READY).is_file():
        raise ToolError(f"start_project {inst.id} first")
    return root, inst


# ----- the project's environment, outside the workspace -----


def scratch_for(workspace: Path, project: str) -> Path:
    """The project's folder in the workspace's scratch home (venv, wheels, run folders)."""
    folder = scratch_home(workspace) / project
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def venv_dir(workspace: Path, project: str) -> Path:
    return scratch_for(workspace, project) / ".venv"


def venv_python(workspace: Path, project: str) -> Path:
    return venv_dir(workspace, project) / "bin" / "python"


def project_env(workspace: Path, project: str, *, with_python: bool = True) -> dict[str, str]:
    """The environment uv, git and Python run in for ``project``: HOME and TMPDIR in the scratch
    home, the project environment pointed at the venv there."""
    venv = venv_dir(workspace, project)
    extra = {"UV_PROJECT_ENVIRONMENT": str(venv)}
    if with_python and (venv / "bin" / "python").exists():
        extra["UV_PYTHON"] = str(venv / "bin" / "python")
    return clean_env(scratch_home(workspace) / "home", extra=extra)


def ensure_venv(workspace: Path, root: Path, inst: Instance, budget: Budget) -> str | None:
    """Make sure the project's venv exists outside the workspace with the workspace's lock
    installed (a later process finds the scratch folder empty and rebuilds it). Returns None when
    it is ready, or what to do when the budget ran out first."""
    venv = venv_dir(workspace, inst.id)
    mark = venv / INSTALLED_MARK
    if mark.is_file():
        return None
    if not budget.allows(20):
        return "call again to rebuild the project's environment"
    if not (venv / "bin" / "python").exists():
        if venv.exists():
            shutil.rmtree(venv, ignore_errors=True)
        made = run([uv(), "venv", "-q", "--python", sys.executable, str(venv)], cwd=root, env=project_env(workspace, inst.id, with_python=False), timeout=budget.slice(VENV_TIMEOUT))
        if made.timed_out:
            shutil.rmtree(venv, ignore_errors=True)
            return "call again to continue rebuilding the project's environment"
        if not made.ok:
            raise ToolError("could not create the project's environment: " + " ".join(made.tail[-3:]))
    if not budget.allows(15):
        return "call again to install the project's environment"
    synced = run([uv(), "sync", "--frozen"], cwd=root, env=project_env(workspace, inst.id), timeout=budget.slice(INSTALL_TIMEOUT))
    if synced.timed_out:
        return "call again to continue installing the project's environment"
    if not synced.ok:
        raise ToolError("could not install the project's locked environment: " + " | ".join(synced.tail[-6:]))
    mark.write_text("installed from uv.lock\n", encoding="utf-8")
    return None


def installed_versions(python: Path, names: list[str], env: dict[str, str]) -> dict[str, str]:
    """Each distribution's version installed in the venv at ``python``, '' when it is missing."""
    if not python.exists():
        return {name: "" for name in names}
    script = (
        "import importlib.metadata as m, json, sys\n"
        "out = {}\n"
        "for name in json.loads(sys.argv[1]):\n"
        "    try:\n"
        "        out[name] = m.version(name)\n"
        "    except m.PackageNotFoundError:\n"
        "        out[name] = ''\n"
        "print(json.dumps(out))\n"
    )
    found = run([str(python), "-I", "-c", script, json.dumps(names)], cwd=python.parent, env=env, timeout=30, tail=5)
    if not found.ok or not found.tail:
        return {name: "" for name in names}
    try:
        return json.loads(found.tail[-1])
    except json.JSONDecodeError:
        return {name: "" for name in names}


def layout_of(root: Path) -> list[str]:
    return [rel for rel, _ in tree_entries(root)][:MAX_LAYOUT]


def uses_of(root: Path, inst: Instance) -> list[str]:
    """The project's source files that import the dependency or one of its collateral packages."""
    modules = [inst.import_name] + [IMPORT_NAMES.get(name, name.replace("-", "_")) for name in inst.allowed_collateral]
    pattern = re.compile(r"^\s*(?:import|from)\s+(?:" + "|".join(re.escape(module) for module in modules) + r")\b", re.MULTILINE)
    found = []
    src = root / "src"
    for path in sorted(src.rglob("*.py")) if src.is_dir() else []:
        if TOOL_DIRS & set(path.relative_to(root).parts):
            continue
        try:
            if pattern.search(path.read_text(encoding="utf-8", errors="replace")):
                found.append(path.relative_to(root).as_posix())
        except OSError:
            continue
    return found[:MAX_USES]


def _start_output(root: Path, inst: Instance, *, complete: bool, next_step: str, current: str) -> StartOutput:
    return StartOutput(
        root=f"dep-upgrade/{inst.id}",
        complete=complete,
        next=next_step,
        dependency=inst.dependency,
        current_version=current,
        target_version=inst.target_version,
        package=inst.package,
        uses_dependency=uses_of(root, inst),
        layout=layout_of(root),
        allowed_new_dependencies=list(inst.allowed_new_dependencies),
        allowed_collateral=list(inst.allowed_collateral),
        rules=rules_for(inst),
        build_hint=inst.build_hint,
        test_hint=inst.test_hint,
    )


def start_project(given: UpgradeInput, workspace: Path, *, budget: Budget | None = None) -> StartOutput:
    """Copy the project into ``dep-upgrade/<project>/``, commit it, and create its venv outside the
    workspace with the locked environment installed. Resumable: each stage is recorded in
    ``.judge/progress.json``; a call that runs out of budget returns ``complete: false`` and the
    next call carries on. A finished project is returned as is (its environment rebuilt first when
    a later process finds it missing)."""
    budget = budget or Budget()
    inst = load_instance(given.project.value)
    root = project_root(workspace, inst.id)
    judge_dir = root / JUDGE_DIR
    ready = judge_dir / READY
    if ready.is_file():
        output = build_output(json.loads(ready.read_text(encoding="utf-8")), StartOutput)
        note = ensure_venv(workspace, root, inst, budget)
        if note:
            return dataclasses.replace(output, complete=False, next=note)
        return output
    progress = load_progress(root) if root.exists() else {}
    stage = progress.get("start", {}) if isinstance(progress.get("start"), dict) else {}
    if not stage.get("copied"):
        if root.exists():
            shutil.rmtree(root)
        root.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(inst.project_dir, root, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", ".venv"))
        judge_dir.mkdir()
        stage = {"copied": True}
        progress = {"start": stage}
        save_progress(root, progress)
    progress["start"] = stage
    progress["environment"] = f"outside the workspace, in {scratch_home(workspace).name}/{inst.id}/.venv (rebuilt from uv.lock when missing)"

    def pause(note: str) -> StartOutput:
        save_progress(root, progress)
        return _start_output(root, inst, complete=False, next_step=note, current="")

    if not stage.get("committed"):
        if (root / ".git").exists():
            shutil.rmtree(root / ".git")
        env = project_env(workspace, inst.id, with_python=False)
        git = ["git", "-c", "user.name=nanoagent", "-c", "user.email=nanoagent@example.invalid", "-c", "commit.gpgsign=false"]
        for step in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "pristine project"]):
            done = run([*git, *step], cwd=root, env=env, timeout=30)
            if not done.ok:
                raise ToolError(f"git {step[0]} failed: {' '.join(done.tail[-3:])}")
        (root / ".git" / "info").mkdir(exist_ok=True)
        (root / ".git" / "info" / "exclude").write_text(GIT_EXCLUDE, encoding="utf-8")
        stage["committed"] = True
        save_progress(root, progress)

    note = ensure_venv(workspace, root, inst, budget)
    if note:
        return pause(note)
    stage["installed"] = True
    save_progress(root, progress)

    current = installed_versions(venv_python(workspace, inst.id), [inst.dependency], project_env(workspace, inst.id))[inst.dependency]
    if current != inst.from_version:
        raise ToolError(f"the environment holds {inst.dependency} {current!r}, expected {inst.from_version}")
    check_workspace_sizes(root)
    output = _start_output(root, inst, complete=True, next_step="", current=current)
    ready.write_text(json.dumps(plain_output(output), indent=1) + "\n", encoding="utf-8")
    prune_scratch(scratch_home(workspace))
    return output
