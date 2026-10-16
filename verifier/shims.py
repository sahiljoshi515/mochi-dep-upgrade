"""Finding shims in what the upgrade added: the forbidden patterns of an instance, matched against the
lines added to its changed files only (never against the code that was already there). The judge and
the verifier both call :func:`scan`."""

import difflib
import json
import re
from pathlib import Path

from .trees import text_lines

MAX_FOUND = 30


def added_with_numbers(before, after):
    """``(line number in after, text)`` of every line of ``after`` new against ``before``."""
    found = []
    for tag, _, _, start, end in difflib.SequenceMatcher(None, before, after, autojunk=False).get_opcodes():
        if tag in ("replace", "insert"):
            found.extend((index + 1, after[index]) for index in range(start, end))
    return found


def added_lines_by_file(root, changed):
    """path -> ``[(line number, text)]`` added, for every added or modified file in ``changed``
    (``[{"path", "status"}]``), against the pristine copies under ``root/.judge/pristine``."""
    root = Path(root)
    out = {}
    for item in changed:
        rel = item["path"]
        if item["status"] == "deleted":
            continue
        after = text_lines((root / rel).read_bytes())
        if item["status"] == "added":
            before = []
        else:
            pristine = root / ".judge" / "pristine" / rel
            before = text_lines(pristine.read_bytes()) if pristine.is_file() else []
        out[rel] = added_with_numbers(before, after)
    return out


def scan(root, changed, patterns):
    """``path:line: pattern`` for every added line matching a forbidden pattern, at most 30."""
    compiled = []
    for pattern in patterns:
        compiled.append((pattern, re.compile(pattern)))
    found = []
    for rel, lines in added_lines_by_file(root, changed).items():
        if not rel.endswith(".py"):
            continue
        for number, text in lines:
            for pattern, regex in compiled:
                if regex.search(text):
                    found.append(f"{rel}:{number}: {pattern}")
                    if len(found) >= MAX_FOUND:
                        return found
    return found


def pristine_manifest(root):
    """The pristine record start_upgrade wrote: ``{"instance", "tree_sha256", "files": {path: sha256}}``,
    or None when it is missing or unreadable."""
    path = Path(root) / ".judge" / "pristine.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        return None
    return data
