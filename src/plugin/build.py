"""Locking, installing, building and testing a project in its venv outside the workspace: the
agent's ``sync`` (resumable), ``run_build`` and ``run_tests``, and the runs the judge shares."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from contract import BuildOutput, SyncOutput, TestsInput, TestsOutput, UpgradeInput
from plugin.common import (
    Budget,
    Completed,
    ToolError,
    check_workspace_sizes,
    load_progress,
    run,
    save_progress,
    scratch_home,
    scrub,
    sha256_file,
    uv,
)
from plugin.instances import Instance
from plugin.project import (
    INSTALLED_MARK,
    direct_dependency_names,
    ensure_venv,
    installed_versions,
    project_env,
    ready_root,
    scratch_for,
    venv_dir,
    venv_python,
)

RUNNER = Path(__file__).with_name("runners") / "pytest_json.py"
LOCK_TIMEOUT = 90.0
SYNC_TIMEOUT = 120.0
BUILD_TIMEOUT = 120.0
TESTS_TIMEOUT = 120.0
MAX_TARGETS = 50
INI = "[pytest]\naddopts =\nfilterwarnings =\n"


def direct_names(root: Path, inst: Instance) -> list[str]:
    """The project's direct dependencies as pyproject.toml names them now, the target first."""
    import tomllib

    try:
        data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        names = direct_dependency_names(data)
    except (OSError, tomllib.TOMLDecodeError, ValueError):
        names = []
    return [inst.dependency] + [name for name in names if name != inst.dependency.lower()]


def sync(given: UpgradeInput, workspace: Path, *, budget: Budget | None = None) -> SyncOutput:
    """``uv lock`` then ``uv sync`` into the project's venv. A resolution or install failure comes
    back as ``ok: false`` with the log's tail; a call that runs out of budget comes back as
    ``complete: false`` with the stage recorded, so the next call carries on."""
    budget = budget or Budget()
    root, inst = ready_root(workspace, given.project.value)
    progress = load_progress(root)
    stage = progress.setdefault("sync", {})
    tail: list[str] = []
    python = venv_python(workspace, inst.id)

    def answer(*, ok: bool, complete: bool, next_step: str) -> SyncOutput:
        save_progress(root, progress)
        installed = installed_versions(python, direct_names(root, inst), project_env(workspace, inst.id))
        return SyncOutput(ok=ok, complete=complete, next=next_step, installed=installed, tail=scrub(tail[-60:], workspace, env=scratch_home(workspace)), seconds=round(budget.spent, 2))

    note = ensure_venv(workspace, root, inst, budget)
    if note:
        return answer(ok=False, complete=False, next_step=note)
    env = project_env(workspace, inst.id)
    pyproject_sha = sha256_file(root / "pyproject.toml")
    if stage.get("locked_for") != pyproject_sha:
        if not budget.allows(15):
            return answer(ok=False, complete=False, next_step="call sync again to lock")
        locked = run([uv(), "lock"], cwd=root, env=env, timeout=budget.slice(LOCK_TIMEOUT))
        tail += locked.tail
        if locked.timed_out:
            return answer(ok=False, complete=False, next_step="call sync again to continue locking")
        if not locked.ok:
            return answer(ok=False, complete=True, next_step="")
        stage["locked_for"] = pyproject_sha
        stage.pop("synced_for", None)
        save_progress(root, progress)

    lock_sha = sha256_file(root / "uv.lock")
    if stage.get("synced_for") != lock_sha:
        if not budget.allows(15):
            return answer(ok=False, complete=False, next_step="call sync again to install the locked environment")
        synced = run([uv(), "sync"], cwd=root, env=env, timeout=budget.slice(SYNC_TIMEOUT))
        tail += synced.tail
        if synced.timed_out:
            return answer(ok=False, complete=False, next_step="call sync again to continue installing")
        if not synced.ok:
            return answer(ok=False, complete=True, next_step="")
        stage["synced_for"] = lock_sha
        (venv_dir(workspace, inst.id) / INSTALLED_MARK).write_text("installed from uv.lock\n", encoding="utf-8")
    check_workspace_sizes(root)
    return answer(ok=True, complete=True, next_step="")


def build_wheel(root: Path, env: dict[str, str], out_dir: Path, timeout: float) -> tuple[Completed, str]:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    done = run([uv(), "build", "--wheel", "--out-dir", str(out_dir), "."], cwd=root, env=env, timeout=timeout)
    wheels = sorted(out_dir.glob("*.whl"))
    return done, (wheels[-1].name if done.ok and wheels else "")


def run_build(given: UpgradeInput, workspace: Path, *, budget: Budget | None = None) -> BuildOutput:
    budget = budget or Budget()
    root, inst = ready_root(workspace, given.project.value)
    note = ensure_venv(workspace, root, inst, budget)
    if note:
        raise ToolError(f"the project's environment is being rebuilt: {note}")
    done, wheel = build_wheel(root, project_env(workspace, inst.id), scratch_for(workspace, inst.id) / "dist", budget.slice(BUILD_TIMEOUT))
    check_workspace_sizes(root)
    return BuildOutput(ok=bool(wheel), wheel=wheel, tail=scrub(done.tail, workspace, env=scratch_home(workspace)), seconds=done.seconds)


@dataclass
class TestRun:
    command: str
    exit_status: int
    tail: list[str]
    seconds: float
    timed_out: bool = False
    collected: list[str] = field(default_factory=list)
    outcomes: dict[str, str] = field(default_factory=dict)
    messages: dict[str, str] = field(default_factory=dict)
    collection_errors: dict[str, str] = field(default_factory=dict)
    report_read: bool = False

    @property
    def passed(self) -> list[str]:
        return [test for test in self.collected if self.outcomes.get(test) == "passed"]

    @property
    def not_passed(self) -> list[str]:
        return [test for test in self.collected if self.outcomes.get(test) != "passed"]

    @property
    def ok(self) -> bool:
        """Every collected test passed, nothing failed to collect, and pytest said so."""
        return (
            self.report_read
            and self.exit_status == 0
            and bool(self.collected)
            and not self.collection_errors
            and not self.not_passed
        )

    def record(self) -> dict:
        return {
            "ok": self.ok,
            "command": self.command,
            "exit_status": self.exit_status,
            "collected": self.collected,
            "outcomes": self.outcomes,
            "messages": self.messages,
            "collection_errors": self.collection_errors,
            "tail": self.tail,
            "seconds": self.seconds,
        }


def run_pytest(
    root: Path,
    env: dict[str, str],
    inst: Instance,
    *,
    python: Path,
    rundir: Path,
    rootdir: Path,
    targets: list[str],
    timeout: float,
    hidden_paths: tuple[Path, ...] = (),
) -> TestRun:
    """Run pytest with the venv's ``python``, the recorder plugin and the project's warning flags,
    on ``targets`` relative to ``rootdir``; the project's own pytest configuration is ignored and
    ``src/`` is first on the path. ``rundir`` holds the plugin, the ini and the report."""
    # Resolved paths only: pytest names tests relative to the rootdir and a symlinked temp folder
    # (macOS /var -> /private/var) would leave it with absolute ids.
    root, rundir, rootdir = root.resolve(), rundir.resolve(), rootdir.resolve()
    rundir.mkdir(parents=True, exist_ok=True)
    shutil.copy(RUNNER, rundir / "nanoagent_pytest_json.py")
    (rundir / "pytest.ini").write_text(INI, encoding="utf-8")
    report = rundir / "report.json"
    if report.exists():
        report.unlink()
    flags = ["-q", "-p", "no:cacheprovider", "--tb=short", "-rfE", "-o", "console_output_style=classic", *inst.warning_flags]
    command = [
        str(python),
        "-m",
        "pytest",
        *flags,
        "-p",
        "nanoagent_pytest_json",
        f"--nanoagent-json={report}",
        "-c",
        str(rundir / "pytest.ini"),
        f"--rootdir={rootdir}",
        f"--basetemp={rundir / 'basetemp'}",
        *targets,
    ]
    run_env = {**env, "PYTHONPATH": os.pathsep.join([str(rundir), str(root / "src")])}
    done = run(command, cwd=rootdir, env=run_env, timeout=timeout)
    result = TestRun(
        command="pytest " + " ".join([*flags, *targets]),
        exit_status=done.code,
        tail=scrub(done.tail, root, *hidden_paths, env=rundir.parent),
        seconds=done.seconds,
        timed_out=done.timed_out,
    )
    if report.is_file():
        try:
            data = json.loads(report.read_text(encoding="utf-8"))
            result.collected = list(data.get("collected", []))
            result.outcomes = dict(data.get("outcomes", {}))
            result.messages = dict(data.get("messages", {}))
            result.collection_errors = dict(data.get("collection_errors", {}))
            result.report_read = True
        except (json.JSONDecodeError, AttributeError, TypeError):
            result.report_read = False
    return result


def check_targets(root: Path, targets: list[str]) -> list[str]:
    if len(targets) > MAX_TARGETS:
        raise ToolError(f"at most {MAX_TARGETS} tests per run")
    cleaned = []
    for target in targets:
        target = target.strip()
        file_part = target.split("::", 1)[0]
        if not target or target.startswith("-") or "\0" in target or Path(file_part).is_absolute() or ".." in Path(file_part).parts:
            raise ToolError(f"not a test path: {target!r}")
        if file_part != "tests" and not file_part.startswith("tests/"):
            raise ToolError(f"tests live under tests/: {target!r}")
        if not (root / file_part).exists():
            raise ToolError(f"no such test file: {file_part}")
        cleaned.append(target)
    return cleaned or ["tests"]


def run_tests(given: TestsInput, workspace: Path, *, budget: Budget | None = None) -> TestsOutput:
    """The project's public tests, in its venv, with warnings as errors: a tail and counts."""
    budget = budget or Budget()
    root, inst = ready_root(workspace, given.project.value)
    targets = check_targets(root, given.tests)
    note = ensure_venv(workspace, root, inst, budget)
    if note:
        raise ToolError(f"the project's environment is being rebuilt: {note}")
    result = run_pytest(
        root,
        project_env(workspace, inst.id),
        inst,
        python=venv_python(workspace, inst.id),
        rundir=scratch_for(workspace, inst.id) / "runs" / "public",
        rootdir=root,
        targets=targets,
        timeout=budget.slice(TESTS_TIMEOUT),
    )
    outcomes = result.outcomes
    failed = [test for test, outcome in outcomes.items() if outcome == "failed"]
    errors = [test for test, outcome in outcomes.items() if outcome == "error"]
    errors += [f"{node} (collection)" for node in result.collection_errors]
    check_workspace_sizes(root)
    return TestsOutput(
        command=result.command,
        exit_code=result.exit_status,
        collected=len(result.collected),
        passed=sum(1 for outcome in outcomes.values() if outcome == "passed"),
        failed=len(failed),
        errors=len(errors),
        skipped=sum(1 for outcome in outcomes.values() if outcome in ("skipped", "xfailed")),
        failed_ids=(failed + errors)[:50],
        tail=result.tail,
        seconds=result.seconds,
    )
