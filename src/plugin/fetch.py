"""What the tools fetch from the web, and how: GitHub's codeload tarballs of a commit and PyPI's JSON
for a release, over HTTPS (through the sandbox's proxy when there is one), with retries.

Tarballs unpack with their top folder stripped, regular files only (links and devices are
skipped), each file at most :data:`MAX_FILE` bytes.
"""

from __future__ import annotations

import io
import json
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from plugin.common import ToolError

USER_AGENT = "nanoagent-dep-upgrade/0.2 (+https://github.com/sahiljoshi515/mochi-dep-upgrade)"
CODELOAD = "https://codeload.github.com/{repo}/tar.gz/{commit}"
PYPI_RELEASE = "https://pypi.org/pypi/{name}/{version}/json"
MAX_TARBALL = 40 * 1024 * 1024
MAX_FILE = 8 * 1024 * 1024
RETRY_STATUS = {429, 500, 502, 503, 504}
# Tests may replace this with an object whose .open(request, timeout) answers like urlopen.
OPENER = None


def get(url: str, *, timeout: float = 60.0, attempts: int = 3, most: int = MAX_TARBALL) -> bytes:
    """The body at ``url``; retries on timeouts, connection errors, 429 and 5xx (1 s, then 3 s)."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    problem = ""
    for attempt in range(attempts):
        try:
            opener = OPENER.open if OPENER is not None else urllib.request.urlopen
            with opener(request, timeout=timeout) as response:
                data = response.read(most + 1)
            if len(data) > most:
                raise ToolError(f"{url} is larger than {most // (1024 * 1024)} MB")
            return data
        except urllib.error.HTTPError as error:
            problem = f"HTTP {error.code}"
            if error.code not in RETRY_STATUS:
                break
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
            problem = str(getattr(error, "reason", error))[:120]
        if attempt + 1 < attempts:
            time.sleep((1, 3, 7)[attempt])
    raise ToolError(f"could not fetch {url}: {problem} after {attempts} tries")


def codeload(repo: str, commit: str) -> bytes:
    return get(CODELOAD.format(repo=repo, commit=commit), timeout=90.0)


def pypi_release(name: str, version: str) -> dict:
    """PyPI's JSON for one release: ``{"files": [{"filename", "sha256"}], "yanked": bool}``."""
    data = json.loads(get(PYPI_RELEASE.format(name=name, version=version), timeout=30.0, most=4 * 1024 * 1024))
    files = sorted(({"filename": item["filename"], "sha256": item["digests"]["sha256"]} for item in data.get("urls", [])), key=lambda item: item["filename"])
    return {"files": files, "yanked": bool(data.get("info", {}).get("yanked", False))}


def members(data: bytes) -> list[tuple[str, bytes]]:
    """``(relative path, bytes)`` of every regular file in a gzipped tarball, its top folder
    stripped; absolute or escaping paths and files over :data:`MAX_FILE` are left out."""
    found: list[tuple[str, bytes]] = []
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive:
            if not member.isfile():
                continue
            parts = Path(member.name).parts
            if len(parts) < 2 or Path(member.name).is_absolute() or ".." in parts:
                continue
            rel = Path(*parts[1:]).as_posix()
            if member.size > MAX_FILE:
                # A file this large never belongs in a workspace (the host refuses it); the checkout and
                # the validated tree both leave it out.
                continue
            handle = archive.extractfile(member)
            if handle is None:
                continue
            found.append((rel, handle.read()))
    return found


def unpack(data: bytes, dest: Path, *, keep=None) -> list[str]:
    """Write the tarball's regular files under ``dest`` (top folder stripped); ``keep(rel)`` picks
    which. Returns the relative paths written, sorted."""
    written = []
    for rel, content in members(data):
        if keep is not None and not keep(rel):
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        written.append(rel)
    return sorted(written)
