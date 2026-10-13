"""Checks shared by the tool verifiers. Pure functions of their arguments and the files on disk."""

import re
from pathlib import Path

PREFIX = "dep-upgrade"
JUDGE_DIR = ".judge"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
VERSION = re.compile(r"^\d+(?:\.\d+)*$")
# What write_file may write: pyproject.toml, or a .py file under src/<package>/.
WRITABLE = re.compile(r"^dep-upgrade/[a-z0-9-]+/(?:pyproject\.toml|src/[A-Za-z_][A-Za-z0-9_]*/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+\.py)$")
MAX_TAIL = 60
MAX_WRITE = 200 * 1024


def result(valid, message, *, score=None, **details):
    return {
        "valid": valid,
        "score": float(valid) if score is None else score,
        "message": message,
        "details": details,
    }


def path_problem(path, *, judge_ok=False):
    """What is wrong with a workspace-relative path, or None."""
    if not isinstance(path, str) or not path.strip() or "\0" in path or len(path) > 1024:
        return "path must be a non-empty relative path"
    parts = Path(path).parts
    if Path(path).is_absolute() or ".." in parts:
        return "path must stay inside the workspace"
    if not judge_ok and JUDGE_DIR in parts:
        return f"{JUDGE_DIR}/ is reserved for the judge"
    return None


def project_root(workspace, project):
    """The project's folder in the workspace: ``dep-upgrade/<project>``."""
    return Path(workspace) / PREFIX / project.value


def is_sha(text):
    return isinstance(text, str) and bool(HEX64.fullmatch(text))


def is_version(text):
    return isinstance(text, str) and bool(VERSION.fullmatch(text))


def tail_problem(tail):
    if len(tail) > MAX_TAIL:
        return f"tail holds {len(tail)} lines, over {MAX_TAIL}"
    return None
