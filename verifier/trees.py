"""The project tree as both the tools and the verifier see it: which files count, their hashes, what
changed against the pristine manifest, how many lines were added, and the editable globs.

A project's files are every regular file under its root except what Python and pytest create
(:data:`SKIP` folders, ``.pyc``) and the judge's own folder; symlinks never count.
"""

import difflib
import hashlib
import re
from pathlib import Path

SKIP = frozenset({".judge", ".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".DS_Store"})


def sha256_of(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def counts(rel):
    """Whether the project-relative path ``rel`` is a project file (not tool output)."""
    parts = rel.split("/")
    return not (SKIP & set(parts)) and not rel.endswith(".pyc")


def tree_entries(root):
    """``(relative path, sha256)`` of every project file under ``root``, sorted."""
    root = Path(root)
    entries = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if not counts(rel) or path.is_symlink() or not path.is_file():
            continue
        entries.append((rel, sha256_of(path)))
    return entries


def tree_hash(entries):
    """sha256 over sorted ``"<path>\\0<sha256>\\n"`` lines."""
    digest = hashlib.sha256()
    for rel, sha in sorted(entries):
        digest.update(f"{rel}\0{sha}\n".encode())
    return digest.hexdigest()


def changes(manifest, entries):
    """Every difference between the pristine ``manifest`` (path -> sha256) and the current
    ``entries``: ``[{"path", "status", "sha256"}]`` sorted by path; status added, modified or deleted."""
    current = dict(entries)
    found = []
    for rel in sorted(set(manifest) | set(current)):
        if rel not in current:
            found.append({"path": rel, "status": "deleted", "sha256": ""})
        elif rel not in manifest:
            found.append({"path": rel, "status": "added", "sha256": current[rel]})
        elif manifest[rel] != current[rel]:
            found.append({"path": rel, "status": "modified", "sha256": current[rel]})
    return found


def text_lines(data):
    """Bytes as text lines (UTF-8, undecodable bytes replaced), without line breaks."""
    return data.decode("utf-8", errors="replace").splitlines()


def added_lines(before, after):
    """The lines of ``after`` that are new against ``before`` (both lists of lines), in order."""
    new = []
    for tag, _, _, start, end in difflib.SequenceMatcher(None, before, after, autojunk=False).get_opcodes():
        if tag in ("replace", "insert"):
            new.extend(after[start:end])
    return new


def unified(path, before, after, context=3):
    """A unified diff of one file as text lines."""
    return list(difflib.unified_diff(before, after, f"a/{path}", f"b/{path}", n=context, lineterm=""))


def glob_regex(pattern):
    """A compiled regex for a project-relative glob: ``**/`` any folders, ``*`` within one name,
    ``?`` one character."""
    out = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            out.append("(?:[^/]+/)*")
            index += 3
        elif pattern.startswith("**", index):
            out.append(".*")
            index += 2
        elif pattern[index] == "*":
            out.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            out.append("[^/]")
            index += 1
        else:
            out.append(re.escape(pattern[index]))
            index += 1
    return re.compile("".join(out))


def matches_any(rel, patterns):
    return any(glob_regex(pattern).fullmatch(rel) for pattern in patterns)
