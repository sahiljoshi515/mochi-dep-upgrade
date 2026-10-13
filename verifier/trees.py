"""Tree hashes, exactly as the tools compute them (``plugin.common.tree_entries``/``tree_hash``):
sha256 over sorted ``"<path>\\0<sha256>\\n"`` lines of every regular file, skipping what git, uv,
Python and pytest create."""

import hashlib
from pathlib import Path

SKIP = frozenset({".git", ".venv", ".judge", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".DS_Store"})


def sha256_of(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree_entries(root, keep=None):
    """``(relative path, sha256)`` of every file under ``root``, sorted, skipping :data:`SKIP` folders,
    ``.pyc`` files and symlinks; ``keep(relative path)`` narrows it."""
    root = Path(root)
    entries = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if SKIP & set(relative.parts) or path.suffix == ".pyc":
            continue
        if path.is_symlink() or not path.is_file():
            continue
        rel = relative.as_posix()
        if keep is not None and not keep(rel):
            continue
        entries.append((rel, sha256_of(path)))
    return entries


def tree_hash(entries):
    digest = hashlib.sha256()
    for rel, sha in sorted(entries):
        digest.update(f"{rel}\0{sha}\n".encode())
    return digest.hexdigest()


def is_protected(rel):
    """Whether the project-relative path ``rel`` may not change: ``README.md`` and ``tests/**``."""
    return rel == "README.md" or rel.split("/", 1)[0] == "tests"
