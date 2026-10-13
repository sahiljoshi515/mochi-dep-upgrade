"""The build-time oracle for the shipped projects. Needs PyPI.

    uv run python -m plugin.tools_dev.check_instances [project ...] [--write-ids]

For each project, in a scratch folder, on this Python:

A. pristine: ``uv sync --frozen``; the public tests pass (plain pytest, no warning flags);
   the hidden tests do NOT all pass (with the project's warning flags);
B. pristine code on the target: the solution's pyproject.toml, ``uv lock`` + ``uv sync``, the
   pristine ``src/``; the public tests do NOT pass under the warning flags (the migration is
   real, not a version bump);
C. solution: ``solution.patch`` applied, ``uv lock`` + ``uv sync`` locks exactly the target,
   ``uv build --wheel`` succeeds, the public and hidden tests pass under the warning flags, and
   the hidden tests collected are exactly ``instance.json``'s ids (``--write-ids`` fills them).
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

from plugin.build import build_wheel, run_pytest
from plugin.common import clean_env, run, uv
from plugin.instances import Instance, all_instances, load_instance
from plugin.project import installed_versions, locked_versions
from plugin.tools_dev.patches import apply_patch, copy_project
from verifier.pyproject import dependencies
from verifier.versions import canonical_name


def plain(inst: Instance) -> Instance:
    """The same instance without warning flags (for the pristine baseline)."""
    return Instance(**{**inst.__dict__, "warning_flags": ()})


def prepare(root: Path, *, frozen: bool) -> dict[str, str]:
    env = clean_env(root / ".judge" / "home", extra={"UV_PROJECT_ENVIRONMENT": str(root / ".venv")})
    made = run([uv(), "venv", "-q", "--python", sys.executable, str(root / ".venv")], cwd=root, env=env, timeout=60)
    if not made.ok:
        raise RuntimeError("uv venv failed: " + "\n".join(made.tail))
    if not frozen:
        locked = run([uv(), "lock"], cwd=root, env=env, timeout=120)
        if not locked.ok:
            raise RuntimeError("uv lock failed: " + "\n".join(locked.tail))
    synced = run([uv(), "sync"] + (["--frozen"] if frozen else []), cwd=root, env=env, timeout=150)
    if not synced.ok:
        raise RuntimeError("uv sync failed: " + "\n".join(synced.tail))
    return env


def pytest_in(root: Path, env: dict[str, str], inst: Instance, kind: str, tests_dir: Path):
    rundir = root / ".judge" / "runs" / kind
    if rundir.exists():
        shutil.rmtree(rundir)
    rundir.mkdir(parents=True)
    if kind.startswith("hidden"):
        names = sorted(path.name for path in tests_dir.glob("test_hidden_*.py"))
        for name in names:
            shutil.copy(tests_dir / name, rundir / name)
        return run_pytest(root, env, inst, rundir=rundir, rootdir=rundir, targets=names, timeout=120)
    shutil.copytree(tests_dir, rundir / "tests", ignore=shutil.ignore_patterns("__pycache__"))
    return run_pytest(root, env, inst, rundir=rundir, rootdir=rundir, targets=["tests"], timeout=120)


def check(inst: Instance, scratch: Path, *, write_ids: bool) -> list[str]:
    problems: list[str] = []
    dep = canonical_name(inst.dependency)
    started = time.perf_counter()

    # A. pristine on the old version
    pristine = copy_project(inst, scratch / "pristine")
    env = prepare(pristine, frozen=True)
    installed = installed_versions(pristine, [inst.dependency], env)[inst.dependency]
    if installed != inst.from_version:
        problems.append(f"A: pristine installs {inst.dependency} {installed}, not {inst.from_version}")
    public = pytest_in(pristine, env, plain(inst), "public", inst.project_dir / "tests")
    if not public.ok:
        problems.append(f"A: pristine public tests fail on {inst.from_version}: {public.not_passed[:3]} {public.collection_errors}")
    hidden = pytest_in(pristine, env, inst, "hidden", inst.hidden_dir)
    if hidden.ok:
        problems.append("A: pristine passes the hidden tests (they do not need the upgrade)")
    print(f"  A pristine@{inst.from_version}: public {len(public.passed)}/{len(public.collected)} passed; hidden {len(hidden.passed)}/{len(hidden.collected)} passed, {len(hidden.collection_errors)} collection errors")

    # B. pristine code on the target version
    bumped = copy_project(inst, scratch / "bumped")
    solution_files = solution_tree(inst, scratch / "solution-tree")
    shutil.copy(solution_files / "pyproject.toml", bumped / "pyproject.toml")
    env_b = prepare(bumped, frozen=False)
    installed_b = installed_versions(bumped, [inst.dependency], env_b)[inst.dependency]
    public_b = pytest_in(bumped, env_b, inst, "public", inst.project_dir / "tests")
    if public_b.ok:
        problems.append("B: the pristine code passes the public tests on the target (a version bump would do)")
    print(f"  B pristine code@{installed_b}: public {len(public_b.passed)}/{len(public_b.collected)} passed, {len(public_b.collection_errors)} collection errors")

    # C. the solution
    solved = copy_project(inst, scratch / "solved")
    apply_patch(solved, inst.solution_patch)
    env_c = prepare(solved, frozen=False)
    installed_c = installed_versions(solved, [inst.dependency], env_c)[inst.dependency]
    if installed_c != inst.target_version:
        problems.append(f"C: the solution installs {inst.dependency} {installed_c}, not {inst.target_version}")
    locked = locked_versions((solved / "uv.lock").read_text(encoding="utf-8"))
    if locked.get(dep) != inst.target_version:
        problems.append(f"C: the solution locks {inst.dependency} {locked.get(dep)}, not {inst.target_version}")
    written = dependencies((solved / "pyproject.toml").read_text(encoding="utf-8"))
    print(f"  C solution dependencies: {written}")
    built, wheel = build_wheel(solved, env_c, solved / ".judge" / "dist", 120)
    if not wheel:
        problems.append("C: uv build --wheel failed: " + " | ".join(built.tail[-5:]))
    public_c = pytest_in(solved, env_c, inst, "public", inst.project_dir / "tests")
    if not public_c.ok:
        problems.append(f"C: the solution fails public tests: {public_c.not_passed[:5]} {public_c.collection_errors} {public_c.messages}")
    hidden_c = pytest_in(solved, env_c, inst, "hidden", inst.hidden_dir)
    if not hidden_c.ok:
        problems.append(f"C: the solution fails hidden tests: {hidden_c.not_passed[:5]} {hidden_c.collection_errors} {hidden_c.messages}")
    ids = sorted(hidden_c.collected)
    if write_ids:
        path = inst.root / "instance.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["hidden_test_ids"] = ids
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"  wrote {len(ids)} hidden test ids")
    elif ids != sorted(inst.hidden_test_ids):
        problems.append(f"C: hidden test ids differ from instance.json: {ids}")
    print(
        f"  C solution@{installed_c}: wheel {wheel or 'FAILED'}; public {len(public_c.passed)}/{len(public_c.collected)};"
        f" hidden {len(hidden_c.passed)}/{len(hidden_c.collected)}; {time.perf_counter() - started:.0f} s in all"
    )
    for name, tail in (("A hidden", hidden.tail), ("B public", public_b.tail)):
        print(f"  {name} tail: " + " | ".join(line for line in tail[-4:]))
    return problems


def solution_tree(inst: Instance, into: Path) -> Path:
    """The solution's files, by applying the patch onto a pristine copy."""
    root = copy_project(inst, into)
    apply_patch(root, inst.solution_patch)
    return root


def main(argv: list[str]) -> int:
    write_ids = "--write-ids" in argv
    names = [arg for arg in argv if not arg.startswith("--")]
    instances = [load_instance(name) for name in names] if names else all_instances()
    failed = 0
    for inst in instances:
        print(f"== {inst.id}: {inst.dependency} {inst.from_version} -> {inst.target_version}")
        with tempfile.TemporaryDirectory(prefix=f"dep-upgrade-oracle-{inst.id}-") as scratch:
            try:
                problems = check(inst, Path(scratch).resolve(), write_ids=write_ids)
            except Exception as error:  # noqa: BLE001 - every failure is reported, the run goes on
                problems = [f"{type(error).__name__}: {error}"]
        for problem in problems:
            print(f"  PROBLEM {problem}")
        print("  OK" if not problems else f"  FAILED ({len(problems)})")
        failed += bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
