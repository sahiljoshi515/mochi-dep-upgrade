"""The agent's ``sync`` (re-lock from the spec as it stands, then install exactly that lock) and
``run_tests`` (the repository's tests in a scratch copy of the project)."""

from __future__ import annotations

from pathlib import Path

from contract import SyncOutput, TestsInput, TestsOutput, UpgradeInput
from plugin import envs
from plugin.common import JUDGE_DIR, Budget, ToolError, check_workspace_sizes, scratch_for, scrub
from plugin.project import LOCK, ensure_env, ready_root
from plugin.spec import read as read_spec
from plugin.testing import copy_tree, run_suite
from verifier.versions import canonical_name

TESTS_TIMEOUT = 120.0
MAX_TARGETS = 50
MAX_FAILED = 30


def spec_requirements(root: Path, entry: dict) -> list[str]:
    spec_file = entry["spec"]["file"]
    return read_spec(entry["spec"]["kind"], (root / spec_file).read_bytes().decode("utf-8"), name=spec_file)[0]


def relock(root: Path, entry: dict, scratch: Path, budget: Budget) -> tuple[str, list[str], bool]:
    """``(lock text or '', tail, timed out)``: the spec as it stands, resolved with everything else
    held at its pre-upgrade version."""
    requirements = spec_requirements(root, entry)
    done, text = envs.compile_lock(entry, requirements, scratch, constraints=envs.constraints_for(entry), timeout=budget.slice(envs.LOCK_TIMEOUT))
    return text, scrub(done.tail, root, env=scratch), done.timed_out


def sync(given: UpgradeInput, workspace: Path, *, budget: Budget | None = None) -> SyncOutput:
    """Re-lock and install. A spec that does not resolve (or cannot be read) comes back as
    ``ok: false`` with the reason; the previous lock and environment stay."""
    budget = budget or Budget()
    root, entry = ready_root(workspace, given.instance.value)
    scratch = scratch_for(workspace, entry["id"])
    dependency = canonical_name(entry["dependency"])

    def answer(*, ok: bool, complete: bool, next_step: str, requirement: str, lock_text: str, tail: list[str]) -> SyncOutput:
        installed = envs.installed_versions(scratch, [entry["dependency"]])[entry["dependency"]] if ok else ""
        return SyncOutput(
            ok=ok,
            complete=complete,
            next=next_step,
            requirement=requirement,
            locked_version=",".join(envs.lock_versions(lock_text).get(dependency, [])) if lock_text else "",
            installed_version=installed,
            changes=envs.lock_changes(entry, lock_text) if lock_text else [],
            tail=tail[-40:],
            seconds=round(budget.spent, 2),
        )

    try:
        requirement = envs.dependency_requirement(entry, spec_requirements(root, entry))
        lock_text, tail, timed_out = relock(root, entry, scratch, budget)
    except ToolError as error:
        return answer(ok=False, complete=True, next_step="", requirement="", lock_text="", tail=[str(error)])
    if timed_out:
        return answer(ok=False, complete=False, next_step="call sync again: locking did not finish", requirement=requirement, lock_text="", tail=tail)
    if not lock_text:
        return answer(ok=False, complete=True, next_step="", requirement=requirement, lock_text="", tail=tail or ["the spec did not resolve"])
    lock_path = root / JUDGE_DIR / LOCK
    if not lock_path.is_file() or lock_path.read_text(encoding="utf-8") != lock_text:
        lock_path.write_text(lock_text, encoding="utf-8")
    note = envs.ensure_venv(entry, scratch, lock_text, budget)
    if note:
        return answer(ok=False, complete=False, next_step=note, requirement=requirement, lock_text=lock_text, tail=[])
    check_workspace_sizes(root)
    return answer(ok=True, complete=True, next_step="", requirement=requirement, lock_text=lock_text, tail=[])


def check_targets(entry: dict, targets: list[str]) -> list[str]:
    if len(targets) > MAX_TARGETS:
        raise ToolError(f"at most {MAX_TARGETS} tests per run")
    dirs = entry["test_dirs"]
    cleaned = []
    for target in targets:
        target = target.strip()
        file_part = target.split("::", 1)[0]
        if not target or target.startswith("-") or "\0" in target or Path(file_part).is_absolute() or ".." in Path(file_part).parts:
            raise ToolError(f"not a test path: {target!r}")
        if not any(file_part == folder or file_part.startswith(folder.rstrip("/") + "/") for folder in dirs):
            raise ToolError(f"tests live under {', '.join(dirs)}: {target!r}")
        cleaned.append(target)
    return cleaned or list(dirs)


def run_tests(given: TestsInput, workspace: Path, *, budget: Budget | None = None) -> TestsOutput:
    """The repository's tests on the agent's code, in the current environment. Failures among tests
    that are not judged are only counted."""
    budget = budget or Budget()
    root, entry = ready_root(workspace, given.instance.value)
    targets = check_targets(entry, given.tests)
    note = ensure_env(workspace, root, entry, budget)
    if note:
        raise ToolError(f"the project's environment is being rebuilt: {note}")
    scratch = scratch_for(workspace, entry["id"])
    tree = copy_tree(root, scratch / "runs" / "tree")
    result = run_suite(tree, entry, scratch, rundir=scratch / "runs" / "public", targets=targets, timeout=budget.slice(TESTS_TIMEOUT))
    judged = set(entry["public"]["ids"])
    bad = sorted(test for test, outcome in result.outcomes.items() if outcome in ("failed", "error"))
    failed = [test for test in bad if test in judged] + [f"{node} (collection)" for node in result.collection_errors]
    outcomes = list(result.outcomes.values())
    return TestsOutput(
        command=result.command,
        exit_code=result.exit_status,
        collected=len(result.collected),
        passed=outcomes.count("passed"),
        failed=outcomes.count("failed"),
        errors=outcomes.count("error") + len(result.collection_errors),
        skipped=outcomes.count("skipped") + outcomes.count("xfailed"),
        failed_ids=failed[:MAX_FAILED],
        excluded_failures=sum(1 for test in bad if test not in judged),
        tail=result.tail,
        seconds=result.seconds,
    )
