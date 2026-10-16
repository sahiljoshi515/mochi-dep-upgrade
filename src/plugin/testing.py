"""Running a project's tests: pytest with the project's own configuration plus the instance's
recorded arguments, in a scratch copy of the tree (so tests never write into the workspace), with
a recorder plugin that writes every test's outcome as JSON."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from plugin.common import run, scrub
from plugin.envs import env_for, venv_python
from verifier.trees import SKIP

RUNNER = Path(__file__).with_name("runners") / "pytest_json.py"
PROXY_VARIABLES = frozenset({"https_proxy", "http_proxy", "all_proxy", "no_proxy"})
NO_NETWORK = '(version 1)(allow default)(deny network-outbound)(allow network-outbound (remote unix-socket))(allow network-outbound (remote ip "localhost:*"))'


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

    def outcome(self, test: str) -> str:
        """passed, failed, error, skipped, xfailed, xpassed, or missing (never collected)."""
        if test not in self.outcomes:
            return "missing"
        return self.outcomes[test]


def copy_tree(source: Path, dest: Path) -> Path:
    """A scratch copy of a project tree without the judge's folder and tool caches."""
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source, dest, ignore=shutil.ignore_patterns(*SKIP, "*.pyc"), symlinks=False)
    return dest


def run_suite(tree: Path, entry: dict, scratch: Path, *, rundir: Path, targets: list[str], timeout: float, hidden: tuple[Path, ...] = (), isolate: bool = False) -> TestRun:
    """pytest on ``targets`` (relative to ``tree``) with the scratch venv's Python; ``rundir`` holds
    the recorder and its report. Paths are resolved first: pytest names tests relative to its
    rootdir, and a symlinked temp folder would leave it with absolute ids."""
    tree, rundir = tree.resolve(), rundir.resolve()
    rundir.mkdir(parents=True, exist_ok=True)
    shutil.copy(RUNNER, rundir / "nanoagent_pytest_json.py")
    report = rundir / "report.json"
    if report.exists():
        report.unlink()
    flags = ["-p", "no:cacheprovider", "--continue-on-collection-errors", *entry.get("pytest_args", [])]
    command = [
        str(venv_python(scratch)), "-m", "pytest", *flags,
        "-p", "nanoagent_pytest_json", f"--nanoagent-json={report}",
        f"--rootdir={tree}", f"--basetemp={rundir / 'basetemp'}",
        *targets,
    ]
    paths = [str(rundir)] + [str((tree / entry_path).resolve()) for entry_path in entry.get("path_entries", ["."])]
    # Tests never reach the network: no proxy (under a sandbox, direct connections are blocked too).
    env = {key: value for key, value in env_for(scratch).items() if key.lower() not in PROXY_VARIABLES}
    env.update({**entry.get("env", {}), "PYTHONPATH": os.pathsep.join(paths)})
    if isolate and shutil.which("sandbox-exec"):
        # The oracle runs outside NanoAgent's sandbox: deny outbound connections but loopback, as the judge's runs see it.
        command = ["sandbox-exec", "-p", NO_NETWORK, *command]
    done = run(command, cwd=tree, env=env, timeout=timeout)
    result = TestRun(
        command="pytest " + " ".join([*flags, *targets]),
        exit_status=done.code,
        tail=scrub(done.tail, tree, *hidden, env=scratch),
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


def judged(run: TestRun, ids: list[str]) -> tuple[list[str], list[str]]:
    """``(failed, missing)`` among the judged ``ids``: not passed, and never collected."""
    failed = [test for test in ids if run.outcome(test) not in ("passed", "missing")]
    missing = [test for test in ids if run.outcome(test) == "missing"]
    return failed, missing
