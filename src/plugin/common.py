"""Shared by every tool: path confinement, subprocesses, hashing, the environment uv runs in, and
the budget and progress record that let a long tool stop and resume.

Nothing here names the plugin's own folder in a message: every path a tool reports is relative
to the workspace.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

# Every project lives at <workspace>/dep-upgrade/<project>/.
WORKSPACE_PREFIX = "dep-upgrade"
# The trusted tools' own folder in a project: the judgement, run folders, a HOME for subprocesses.
JUDGE_DIR = ".judge"
PROGRESS = "progress.json"
# What git, uv, Python and pytest create: never listed, searched, hashed or judged.
TOOL_DIRS = frozenset({".git", ".venv", JUDGE_DIR, "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", "dist", "build"})
HASH_SKIP = frozenset({".git", ".venv", JUDGE_DIR, "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".DS_Store"})
# The host's variables a subprocess may keep: how it reaches the index, where uv caches.
PASSTHROUGH_ENV = (
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "NO_PROXY",
    "no_proxy",
    "UV_CACHE_DIR",
    "UV_LINK_MODE",
    "UV_PYTHON_INSTALL_DIR",
    "UV_NATIVE_TLS",
    "UV_CONCURRENT_DOWNLOADS",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
)
TAIL_LINES = 60
MAX_LINE = 200
# Seconds a long tool call may spend before it returns `complete: false` (hosted cap: 180 s
# including the launch).
BUDGET = 140.0
# No tool writes a file this large into the workspace: the host syncs the workspace back and
# refuses files over 10 MB.
MAX_WORKSPACE_FILE = 8 * 1024 * 1024
# Where a workspace's venvs, build output, run folders and subprocess HOME live: outside the
# workspace, under the temp folder, named after the workspace path.
SCRATCH_PREFIX = "nanoagent-dep-upgrade-"
# Scratch folders of other workspaces untouched for this long are removed, best effort.
PRUNE_AFTER = 12 * 3600
# The plugin's own folder: never shown in an output (see scrub).
PLUGIN_ROOT = Path(__file__).resolve().parents[2]


class ToolError(ValueError):
    """A tool refuses: the message is plain and names no plugin path."""


def scrub(lines: Iterable[str], *hidden: Path, env: Path | None = None) -> list[str]:
    """``lines`` with the plugin's folder, the scratch folder ``env`` and any other ``hidden``
    folder replaced by a marker, each cut to :data:`MAX_LINE` characters."""
    out = []
    for line in lines:
        text = line.replace(str(PLUGIN_ROOT), "<plugin>")
        if env is not None:
            text = text.replace(str(env), "<env>")
        for folder in hidden:
            text = text.replace(str(folder), "<workspace>")
        out.append(text[:MAX_LINE])
    return out


def confine(root: Path, rel: str, *, allow_judge: bool = False) -> Path:
    """The path ``rel`` names inside ``root``: relative, without ``..`` or NUL, not under
    ``.judge`` (unless allowed), and not a symlink that leaves ``root``."""
    if not isinstance(rel, str) or not rel.strip() or "\0" in rel:
        raise ToolError("path must be a non-empty relative path")
    relative = Path(rel)
    if relative.is_absolute() or ".." in relative.parts:
        raise ToolError(f"path must stay inside the workspace: {rel}")
    if not allow_judge and JUDGE_DIR in relative.parts:
        raise ToolError(f"{JUDGE_DIR}/ is reserved for the judge: {rel}")
    base = root.resolve()
    resolved = (base / relative).resolve()
    if not resolved.is_relative_to(base):
        raise ToolError(f"path must stay inside the workspace: {rel}")
    return resolved


def project_root(workspace: Path, project: str) -> Path:
    return workspace.resolve() / WORKSPACE_PREFIX / project


def workspace_relative(workspace: Path, path: Path) -> str:
    return path.resolve().relative_to(workspace.resolve()).as_posix()


def is_protected(rel: str) -> bool:
    """Whether the project-relative path ``rel`` is one the task may not change."""
    return rel == "README.md" or rel.split("/", 1)[0] == "tests"


# ----- the scratch folder outside the workspace -----


def scratch_home(workspace: Path) -> Path:
    """``<tmp>/nanoagent-dep-upgrade-<sha256 of the workspace path>``: the one folder outside the
    workspace this plugin writes to (venvs, wheels, run folders, HOME). Under the macOS sandbox
    the temp folder is the sandbox home; on the hosted runner it is /tmp."""
    digest = hashlib.sha256(str(workspace.resolve()).encode("utf-8")).hexdigest()
    return Path(tempfile.gettempdir()).resolve() / f"{SCRATCH_PREFIX}{digest}"


def oversized(root: Path, limit: int = MAX_WORKSPACE_FILE) -> list[tuple[str, int]]:
    """``(relative path, bytes)`` of every file under ``root`` over ``limit``, every folder included."""
    found: list[tuple[str, int]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        size = path.stat().st_size
        if size > limit:
            found.append((path.relative_to(root).as_posix(), size))
    return found


def check_workspace_sizes(root: Path) -> None:
    """Refuse to leave a file over :data:`MAX_WORKSPACE_FILE` in the workspace."""
    big = oversized(root)
    if big:
        rel, size = big[0]
        raise ToolError(f"{rel} is {size} bytes, over the {MAX_WORKSPACE_FILE // (1024 * 1024)} MB limit for files in the workspace")


def prune_scratch(keep: Path, *, older_than: float = PRUNE_AFTER) -> int:
    """Remove other workspaces' scratch folders untouched for ``older_than`` seconds; returns how many."""
    removed = 0
    now = time.time()
    try:
        candidates = list(keep.parent.iterdir())
    except OSError:
        return 0
    for path in candidates:
        if path == keep or not path.name.startswith(SCRATCH_PREFIX) or path.is_symlink() or not path.is_dir():
            continue
        try:
            if now - path.stat().st_mtime < older_than:
                continue
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
        except OSError:
            continue
    return removed


# ----- budget and progress -----


class Budget:
    """The seconds a tool call may still spend."""

    def __init__(self, seconds: float = BUDGET) -> None:
        self.seconds = seconds
        self.started = time.perf_counter()

    @property
    def spent(self) -> float:
        return time.perf_counter() - self.started

    @property
    def left(self) -> float:
        return max(0.0, self.seconds - self.spent)

    def allows(self, needed: float) -> bool:
        return self.left >= needed

    def slice(self, most: float, *, keep: float = 5.0) -> float:
        """A timeout for the next step: at most ``most``, within what is left minus ``keep``."""
        return max(1.0, min(most, self.left - keep))


def load_progress(root: Path) -> dict:
    """The project's progress record (``.judge/progress.json``), or {}."""
    path = root / JUDGE_DIR / PROGRESS
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_progress(root: Path, data: dict) -> None:
    folder = root / JUDGE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    (folder / PROGRESS).write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")


# ----- subprocesses -----


@dataclass(frozen=True)
class Completed:
    code: int
    tail: list[str]
    seconds: float
    timed_out: bool

    @property
    def ok(self) -> bool:
        return self.code == 0 and not self.timed_out


def run(cmd: Sequence[str], *, cwd: Path, env: dict[str, str], timeout: float, tail: int = TAIL_LINES) -> Completed:
    """Run ``cmd`` in its own session; on timeout kill the whole process group. Keeps the last
    ``tail`` lines of combined output, each cut to :data:`MAX_LINE` characters."""
    started = time.perf_counter()
    process = subprocess.Popen(
        list(cmd),
        cwd=str(cwd),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    timed_out = False
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            process.kill()
        output, _ = process.communicate()
    seconds = round(time.perf_counter() - started, 2)
    lines = output.decode("utf-8", errors="replace").splitlines()
    kept = [line[:MAX_LINE] for line in lines[-tail:]] if tail else []
    if timed_out:
        kept.append(f"[stopped after {timeout:.0f} s; call again to continue]")
    return Completed(code=process.returncode, tail=kept, seconds=seconds, timed_out=timed_out)


def clean_env(home: Path, *, extra: dict[str, str] | None = None) -> dict[str, str]:
    """A deterministic environment for git, uv and Python: no user config, no index overrides, no
    warnings filters, no offline mode; the host's proxy and cache settings pass through."""
    home.mkdir(parents=True, exist_ok=True)
    tmp = home / "tmp"
    tmp.mkdir(exist_ok=True)
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(home),
        "TMPDIR": str(tmp),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "NO_COLOR": "1",
        "TERM": "dumb",
        "COLUMNS": "120",
        "UV_NO_PROGRESS": "1",
        "UV_PYTHON_DOWNLOADS": "never",
        "UV_NO_CONFIG": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }
    for name in PASSTHROUGH_ENV:
        if os.environ.get(name):
            env[name] = os.environ[name]
    # Without a cache every call would download again; one cache per machine, outside any workspace.
    env.setdefault("UV_CACHE_DIR", str(Path(tempfile.gettempdir()) / "nanoagent-dep-upgrade" / "uv-cache"))
    if extra:
        env.update(extra)
    return env


def uv() -> str:
    found = shutil.which("uv")
    if not found:
        raise ToolError("uv is not installed")
    return found


# ----- hashing -----


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_entries(root: Path, *, keep: Callable[[str], bool] | None = None) -> list[tuple[str, str]]:
    """``(relative path, sha256)`` of every regular file under ``root``, sorted, skipping
    :data:`HASH_SKIP` folders, ``.pyc`` files and symlinks; ``keep`` narrows it further."""
    entries: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if HASH_SKIP & set(relative.parts) or path.suffix == ".pyc":
            continue
        if path.is_symlink() or not path.is_file():
            continue
        rel = relative.as_posix()
        if keep is not None and not keep(rel):
            continue
        entries.append((rel, sha256_file(path)))
    return entries


def tree_hash(entries: Iterable[tuple[str, str]]) -> str:
    """sha256 over sorted ``"<path>\\0<sha256>\\n"`` lines: the same rule the verifier applies."""
    digest = hashlib.sha256()
    for rel, sha in sorted(entries):
        digest.update(f"{rel}\0{sha}\n".encode())
    return digest.hexdigest()


def tail_of(path: Path, lines: int = TAIL_LINES) -> list[str]:
    try:
        return [line[:MAX_LINE] for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]]
    except OSError:
        return []
