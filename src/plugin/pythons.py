"""The interpreter an instance's environment is built on: its catalog's Python minor version.

In order: the plugin's own interpreter when its minor matches; an interpreter uv already knows
(``uv python find``, never downloading); else a python-build-standalone build from
releases.astral.sh, sha256-pinned per platform in ``data/pythons.json`` and unpacked into the
launch's scratch folder.
"""

from __future__ import annotations

import io
import json
import platform
import sys
import tarfile
from pathlib import Path

from plugin.common import ToolError, clean_env, run, sha256_bytes, uv
from plugin.fetch import get

PYTHONS = Path(__file__).with_name("data") / "pythons.json"


def platform_key() -> str:
    machine = platform.machine().lower()
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x86_64", "amd64": "x86_64"}.get(machine, machine)
    system = {"darwin": "macos", "linux": "linux"}.get(sys.platform, sys.platform)
    return f"{system}-{arch}"


def _own(minor: str) -> Path | None:
    if f"{sys.version_info[0]}.{sys.version_info[1]}" == minor:
        return Path(sys.executable)
    return None


def _known(minor: str, home: Path) -> Path | None:
    found = run([uv(), "python", "find", minor], cwd=home, env=clean_env(home), timeout=30, tail=3)
    if found.ok and found.tail:
        candidate = Path(found.tail[-1].strip())
        if candidate.is_file():
            return candidate
    return None


def _downloaded(minor: str, scratch: Path) -> Path:
    table = json.loads(PYTHONS.read_text(encoding="utf-8"))
    entry = table.get("pythons", {}).get(minor, {}).get(platform_key())
    if not entry:
        raise ToolError(f"no Python {minor} build for {platform_key()}: environments cover macOS (Apple silicon, Intel) and Linux x86-64")
    folder = scratch / f"python-{minor}"
    python = folder / "python" / "bin" / f"python{minor}"
    if python.is_file():
        return python
    data = get(entry["url"], timeout=120.0, most=80 * 1024 * 1024)
    if sha256_bytes(data) != entry["sha256"]:
        raise ToolError(f"the Python {minor} build downloaded for {platform_key()} does not match its pinned sha256")
    folder.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        archive.extractall(folder, filter="data")
    if not python.is_file():
        raise ToolError(f"the Python {minor} build has no python{minor}")
    return python


def python_for(minor: str, scratch: Path) -> Path:
    """The interpreter for ``minor`` (e.g. ``"3.12"``), found or fetched as the module says."""
    return _own(minor) or _known(minor, scratch / "home") or _downloaded(minor, scratch)
