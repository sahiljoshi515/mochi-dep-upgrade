"""Write data/pythons.json: the python-build-standalone build of each Python minor the catalog uses,
per platform, with the sha256 its release publishes (SHA256SUMS on releases.astral.sh).

    uv run python -m plugin.tools_dev.record_pythons [<release> <minor>=<patch> ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from plugin.fetch import get

BASE = "https://releases.astral.sh/github/python-build-standalone/releases/download/{release}/"
TRIPLES = {"macos-arm64": "aarch64-apple-darwin", "macos-x86_64": "x86_64-apple-darwin", "linux-x86_64": "x86_64-unknown-linux-gnu"}
OUT = Path(__file__).resolve().parents[1] / "data" / "pythons.json"


def main(argv: list[str]) -> int:
    release = argv[0] if argv else "20261001"
    versions = dict(arg.split("=", 1) for arg in argv[1:]) or {"3.12": "3.12.15"}
    sums = {}
    for line in get(BASE.format(release=release) + "SHA256SUMS", most=4 * 1024 * 1024).decode().splitlines():
        sha, _, name = line.partition("  ")
        sums[name.strip()] = sha.strip()
    table = {"release": release, "pythons": {}}
    for minor, patch in versions.items():
        table["pythons"][minor] = {"version": patch}
        for key, triple in TRIPLES.items():
            name = f"cpython-{patch}+{release}-{triple}-install_only_stripped.tar.gz"
            if name not in sums:
                raise SystemExit(f"{name} is not in release {release}")
            table["pythons"][minor][key] = {"url": BASE.format(release=release) + name.replace("+", "%2B"), "sha256": sums[name]}
    OUT.write_text(json.dumps(table, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUT.name}: {', '.join(versions)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
