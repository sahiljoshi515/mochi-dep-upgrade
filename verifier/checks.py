"""Shared by the tool verifiers and the task verdict: the result shape, the constraint list, and small
checks. Pure functions of their arguments and the files on disk."""

import re
from pathlib import Path

PREFIX = "dep-upgrade"
JUDGE_DIR = ".judge"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+)*(?:(?:a|b|rc|\.post|\.dev)[0-9]+)*$")
MAX_TAIL = 60


def result(valid, message, *, score=None, **details):
    return {"valid": valid, "score": float(valid) if score is None else score, "message": message, "details": details}


# Names a changed file may not have, wherever it is: pytest, the build or the interpreter would load it as
# configuration. The instance's spec file is exempt (setup.cfg can be the spec).
FORBIDDEN_NAMES = frozenset({"conftest.py", "pytest.ini", "tox.ini", "setup.cfg", "sitecustomize.py", "usercustomize.py"})


def forbidden_problem(inside, spec_file):
    """Why a project-relative path may never change, whatever the instance's globs say, or None. The
    tools (``plugin.files``) and the input verifier both ask this."""
    parts = inside.split("/")
    if any(part.startswith(".") for part in parts) or (parts[-1] in FORBIDDEN_NAMES and inside != spec_file):
        return f"that file may not change: {inside}"
    return None


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


def project_root(workspace, instance_id):
    """The instance's folder in the workspace: ``dep-upgrade/<instance>``."""
    return Path(workspace) / PREFIX / instance_id


def is_sha(text):
    return isinstance(text, str) and bool(HEX64.fullmatch(text))


def is_version(text):
    return isinstance(text, str) and bool(VERSION.fullmatch(text))


def tail_problem(tail):
    if len(tail) > MAX_TAIL:
        return f"tail holds {len(tail)} lines, over {MAX_TAIL}"
    return None


def short(values, most=10):
    """At most ``most`` items of a list, with a count of the rest."""
    values = list(values)
    return values if len(values) <= most else values[:most] + [f"... and {len(values) - most} more"]


class Constraints:
    """The ordered list of every constraint a verdict checks: each ``{id, constraint, ok, expected,
    actual, message}``, where ``ok`` is True, False, or None for not checked (it depends on an
    earlier constraint that failed)."""

    def __init__(self):
        self.items = []

    def add(self, cid, constraint, ok, *, expected=None, actual=None, message=""):
        self.items.append({"id": cid, "constraint": constraint, "ok": ok, "expected": expected, "actual": actual, "message": message})
        return ok

    def skip(self, cid, constraint, reason):
        return self.add(cid, constraint, None, message=f"not checked: {reason}")

    def verdict(self, success, **details):
        """The verdict: valid when every constraint holds; the score is the share that held, at most
        0.99 unless valid; the message names the first failure (or says all hold)."""
        total = len(self.items)
        held = sum(1 for item in self.items if item["ok"] is True)
        valid = held == total
        failed = [item for item in self.items if item["ok"] is not True]
        if valid:
            message = f"All {total} checks hold: {success}"
            score = 1.0
        else:
            first = next((item for item in failed if item["ok"] is False), failed[0])
            message = f"{len(failed)} of {total} checks failed. First: {first['message'] or first['constraint']}"
            score = min(0.99, round(held / total, 4))
        return result(valid, message, score=score, constraints=self.items, **details)
