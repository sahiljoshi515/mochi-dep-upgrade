"""The judge: the trusted, final look at a project, in stages that resume across calls.

Stages: diff (git status against the pristine commit) -> lock check -> build -> public tests from
a pristine copy -> hidden tests -> forbidden-pattern scan. Each stage's result goes into
``.judge/progress.json`` under the hash of the tree it judged; a call that runs out of budget
returns ``complete: false`` and the next call carries on from the first stage not yet done. A
tree that changed since resets every stage. When every stage is done the judge writes
``.judge/judgement.json`` (``complete: true``) with every hash the verifier cross-checks, and
returns counts and the changed files, nothing about the hidden tests. Builds and test runs happen
in the project's venv outside the workspace; the workspace gets only the record."""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

from contract import JudgeOutput, UpgradeInput
from plugin.build import build_wheel, direct_names, run_pytest
from plugin.common import (
    JUDGE_DIR,
    TOOL_DIRS,
    Budget,
    check_workspace_sizes,
    is_protected,
    load_progress,
    run,
    save_progress,
    scratch_home,
    scrub,
    sha256_file,
    tree_entries,
    tree_hash,
    uv,
)
from plugin.instances import Instance
from plugin.project import ensure_venv, installed_versions, project_env, ready_root, scratch_for, venv_python

JUDGEMENT = "judgement.json"
DIFF = "diff.patch"
LOCK_TIMEOUT = 40.0
BUILD_TIMEOUT = 60.0
TESTS_TIMEOUT = 60.0
MAX_VIOLATIONS = 50
STAGES = ("diff", "lock_check", "build", "public", "hidden", "scan")


def _git(root: Path, env: dict[str, str], *args: str, timeout: float = 30.0, tail: int = 2000):
    return run(["git", *args], cwd=root, env=env, timeout=timeout, tail=tail)


def changed_files(root: Path, env: dict[str, str]) -> list[dict]:
    """Every file that differs from the pristine commit: path, status, sha256 and added lines."""
    status = _git(root, env, "status", "--porcelain=v1", "-uall", "--no-renames")
    if not status.ok:
        raise RuntimeError("git status failed: " + " ".join(status.tail[-3:]))
    found: list[dict] = []
    for line in status.tail:
        if len(line) < 4:
            continue
        code, rel = line[:2], line[3:]
        if rel.startswith('"') and rel.endswith('"'):
            rel = rel[1:-1]
        if TOOL_DIRS & set(Path(rel).parts):
            continue
        if code == "??":
            state = "added"
        elif "D" in code:
            state = "deleted"
        else:
            state = "modified"
        path = root / rel
        entry = {"path": rel, "status": state, "sha256": "", "added_lines": 0}
        if state != "deleted" and path.is_file():
            entry["sha256"] = sha256_file(path)
            if state == "added":
                entry["added_lines"] = len(path.read_bytes().splitlines())
            else:
                numstat = _git(root, env, "diff", "--numstat", "HEAD", "--", rel)
                for row in numstat.tail:
                    parts = row.split("\t")
                    if len(parts) == 3 and parts[0].isdigit():
                        entry["added_lines"] = int(parts[0])
        found.append(entry)
    return sorted(found, key=lambda item: item["path"])


def diff_text(root: Path, env: dict[str, str], changed: list[dict]) -> str:
    """A unified diff of every change for the page: tracked files against HEAD, new files whole."""
    tracked = _git(root, env, "diff", "HEAD", "--no-color", tail=4000)
    pieces = ["\n".join(tracked.tail)] if tracked.tail else []
    for entry in changed:
        if entry["status"] == "added":
            new = _git(root, env, "diff", "--no-index", "--no-color", "/dev/null", entry["path"], tail=2000)
            if new.tail:
                pieces.append("\n".join(new.tail))
    return "\n".join(piece for piece in pieces if piece) + "\n"


def scan_forbidden(src: Path, patterns: tuple[str, ...]) -> list[str]:
    """``file:line: pattern`` for every line under ``src`` matching a forbidden pattern."""
    compiled = [(pattern, re.compile(pattern)) for pattern in patterns]
    violations: list[str] = []
    for path in sorted(src.rglob("*.py")):
        if TOOL_DIRS & set(path.relative_to(src).parts):
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        rel = path.relative_to(src.parent).as_posix()
        for number, line in enumerate(lines, 1):
            for pattern, regex in compiled:
                if regex.search(line):
                    violations.append(f"{rel}:{number}: {pattern}")
                    if len(violations) >= MAX_VIOLATIONS:
                        return violations
    return violations


def _test_stage(workspace: Path, root: Path, env: dict[str, str], inst: Instance, kind: str, timeout: float) -> dict:
    """Run the pristine public tests or the hidden tests in a fresh run folder outside the
    workspace; the hidden tests' text is removed again afterwards."""
    rundir = scratch_for(workspace, inst.id) / "runs" / f"judge-{kind}"
    if rundir.exists():
        shutil.rmtree(rundir)
    rundir.mkdir(parents=True)
    python = venv_python(workspace, inst.id)
    if kind == "public":
        shutil.copytree(inst.project_dir / "tests", rundir / "tests", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        result = run_pytest(root, env, inst, python=python, rundir=rundir, rootdir=rundir, targets=["tests"], timeout=timeout)
    else:
        names = sorted(path.name for path in inst.hidden_dir.glob("test_hidden_*.py"))
        for name in names:
            shutil.copy(inst.hidden_dir / name, rundir / name)
        try:
            result = run_pytest(root, env, inst, python=python, rundir=rundir, rootdir=rundir, targets=names, timeout=timeout, hidden_paths=(inst.hidden_dir,))
        finally:
            for name in names:
                (rundir / name).unlink(missing_ok=True)
    record = result.record()
    record["timed_out"] = result.timed_out
    return record


def judge(given: UpgradeInput, workspace: Path, *, budget: Budget | None = None) -> JudgeOutput:
    budget = budget or Budget()
    root, inst = ready_root(workspace, given.project.value)
    judge_dir = root / JUDGE_DIR
    env = project_env(workspace, inst.id)

    tree_now = tree_hash(tree_entries(root))
    progress = load_progress(root)
    state = progress.get("judge") if isinstance(progress.get("judge"), dict) else None
    if not state or state.get("tree") != tree_now or not isinstance(state.get("stages"), dict):
        state = {"tree": tree_now, "stages": {}, "unstable": False}
    stages: dict = state["stages"]

    def persist() -> None:
        # A stage that changed the tree (code run by the tests writing files) marks the judgement.
        if tree_hash(tree_entries(root)) != tree_now:
            state["unstable"] = True
        progress["judge"] = state
        save_progress(root, progress)

    def pause(note: str) -> JudgeOutput:
        persist()
        changed = stages.get("diff", {}).get("changed_files", [])
        public = stages.get("public", {})
        public_passed = sum(1 for outcome in public.get("outcomes", {}).values() if outcome == "passed")
        return JudgeOutput(
            recorded=False,
            complete=False,
            next=note,
            changed_files=[entry["path"] for entry in changed],
            protected_changes=[entry["path"] for entry in changed if is_protected(entry["path"])],
            lock_ok=bool(stages.get("lock_check", {}).get("ok", False)),
            installed_version=stages.get("installed", {}).get(inst.dependency, ""),
            build_ok=bool(stages.get("build", {}).get("ok", False)),
            public_passed=public_passed,
            public_failed=max(0, len(public.get("collected", [])) - public_passed) + len(public.get("collection_errors", {})),
            violations=list(stages.get("scan", {}).get("forbidden", [])),
            seconds=round(budget.spent, 2),
        )

    if "diff" not in stages:
        stages["diff"] = {"changed_files": changed_files(root, env)}
        persist()
    note = ensure_venv(workspace, root, inst, budget)
    if note:
        return pause(f"call judge again to continue: the project's environment is being rebuilt ({note})")
    env = project_env(workspace, inst.id)
    if "lock_check" not in stages:
        if not budget.allows(15):
            return pause("call judge again to continue: lock check, build and tests are left")
        lock = run([uv(), "lock", "--check"], cwd=root, env=env, timeout=budget.slice(LOCK_TIMEOUT))
        if lock.timed_out:
            return pause("call judge again to continue: the lock check did not finish")
        stages["lock_check"] = {"ok": lock.ok, "tail": scrub(lock.tail, workspace, env=scratch_home(workspace))}
        stages["installed"] = installed_versions(venv_python(workspace, inst.id), direct_names(root, inst), env)
        persist()
    if "build" not in stages:
        if not budget.allows(20):
            return pause("call judge again to continue: build and tests are left")
        built, wheel = build_wheel(root, env, scratch_for(workspace, inst.id) / "dist", budget.slice(BUILD_TIMEOUT))
        if built.timed_out:
            return pause("call judge again to continue: the build did not finish")
        stages["build"] = {"ok": bool(wheel), "wheel": wheel, "tail": scrub(built.tail, workspace, env=scratch_home(workspace)), "seconds": built.seconds}
        persist()
    for kind in ("public", "hidden"):
        if kind not in stages:
            if not budget.allows(20):
                return pause(f"call judge again to continue: the {kind} tests are left")
            record = _test_stage(workspace, root, env, inst, kind, budget.slice(TESTS_TIMEOUT))
            if record["timed_out"]:
                return pause(f"call judge again to continue: the {kind} tests did not finish")
            stages[kind] = record
            persist()
    if "scan" not in stages:
        stages["scan"] = {"forbidden": scan_forbidden(root / "src", inst.forbidden_patterns)}
        persist()

    tree_after_entries = tree_entries(root)
    tree_after = tree_hash(tree_after_entries)
    changed = changed_files(root, env)
    stable = tree_after == tree_now and not state.get("unstable") and changed == stages["diff"]["changed_files"]
    public = stages["public"]
    judgement = {
        "version": 1,
        "complete": True,
        "project": inst.id,
        "dependency": inst.dependency,
        "target_version": inst.target_version,
        "package": inst.package,
        "pristine_tree_sha256": tree_hash(tree_entries(inst.project_dir)),
        "hidden_tests_sha256": tree_hash(tree_entries(inst.hidden_dir)),
        "protected_tree_sha256": tree_hash(entry for entry in tree_after_entries if is_protected(entry[0])),
        "tree_sha256": tree_after,
        "tree_stable": stable,
        "pyproject_sha256": sha256_file(root / "pyproject.toml") if (root / "pyproject.toml").is_file() else "",
        "uv_lock_sha256": sha256_file(root / "uv.lock") if (root / "uv.lock").is_file() else "",
        "changed_files": changed,
        "installed": stages["installed"],
        "lock_check": stages["lock_check"],
        "build": stages["build"],
        "public": public,
        "hidden": stages["hidden"],
        "forbidden": stages["scan"]["forbidden"],
        "seconds": round(budget.spent, 2),
        "judged_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (judge_dir / JUDGEMENT).write_text(json.dumps(judgement, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (judge_dir / DIFF).write_text(diff_text(root, env, changed), encoding="utf-8")
    progress.pop("judge", None)
    save_progress(root, progress)
    check_workspace_sizes(root)
    public_passed = sum(1 for outcome in public["outcomes"].values() if outcome == "passed")
    return JudgeOutput(
        recorded=True,
        complete=True,
        next="",
        changed_files=[entry["path"] for entry in changed],
        protected_changes=[entry["path"] for entry in changed if is_protected(entry["path"])],
        lock_ok=bool(stages["lock_check"]["ok"]),
        installed_version=stages["installed"].get(inst.dependency, ""),
        build_ok=bool(stages["build"]["ok"]),
        public_passed=public_passed,
        public_failed=max(0, len(public["collected"]) - public_passed) + len(public["collection_errors"]),
        violations=list(stages["scan"]["forbidden"]),
        seconds=judgement["seconds"],
    )
