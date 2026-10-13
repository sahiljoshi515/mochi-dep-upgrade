"""Solution patches: made from a solution tree, applied onto a pristine copy. Shared by the oracle,
the patch maker and the case maker."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from plugin.common import clean_env
from plugin.instances import Instance

GIT = ["git", "-c", "user.name=nanoagent", "-c", "user.email=nanoagent@example.invalid", "-c", "commit.gpgsign=false"]


def copy_project(inst: Instance, into: Path) -> Path:
    """A fresh copy of the pristine project at ``into`` (created)."""
    shutil.copytree(inst.project_dir, into, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", ".venv"))
    return into


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    env = clean_env(Path(tempfile.gettempdir()) / "nanoagent-dep-upgrade" / "home")
    return subprocess.run([*GIT, *args], cwd=cwd, env=env, capture_output=True, text=True, check=check)


def commit_pristine(root: Path) -> None:
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "pristine project")


def make_patch(inst: Instance, solution: Path) -> str:
    """The unified diff that turns the pristine project into ``solution`` (a tree of the files
    that change, same layout as the project)."""
    with tempfile.TemporaryDirectory(prefix="dep-upgrade-patch-") as scratch:
        root = copy_project(inst, Path(scratch) / "project")
        commit_pristine(root)
        for path in sorted(solution.rglob("*")):
            if path.is_file():
                target = root / path.relative_to(solution)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(path, target)
        git(root, "add", "-A")
        return git(root, "diff", "--cached", "--no-color").stdout


def apply_patch(root: Path, patch: Path) -> None:
    """Apply ``patch`` to the project at ``root`` (no git repository needed)."""
    git(root, "apply", "--whitespace=nowarn", str(patch))


def changed_files_of(inst: Instance) -> dict[str, str]:
    """``{project-relative path: new content}`` for every file ``solution.patch`` touches."""
    with tempfile.TemporaryDirectory(prefix="dep-upgrade-solution-") as scratch:
        root = copy_project(inst, Path(scratch) / "project")
        commit_pristine(root)
        apply_patch(root, inst.solution_patch)
        status = git(root, "status", "--porcelain=v1", "-uall", "--no-renames").stdout
        files = {}
        for line in status.splitlines():
            rel = line[3:]
            if "D" in line[:2]:
                raise ValueError(f"solution.patch deletes {rel}, which write_file cannot do")
            files[rel] = (root / rel).read_text(encoding="utf-8")
        return files
