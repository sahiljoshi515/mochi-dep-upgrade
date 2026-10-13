"""Write ``solution.patch`` for a project from a solution tree.

    uv run python -m plugin.tools_dev.make_solution_patch <project> <solution tree>

The tree holds only the files that change (``pyproject.toml``, ``src/<package>/*.py``), in the
project's layout.
"""

from __future__ import annotations

import sys
from pathlib import Path

from plugin.instances import load_instance
from plugin.tools_dev.patches import make_patch


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    inst = load_instance(argv[0])
    patch = make_patch(inst, Path(argv[1]).resolve())
    if not patch.strip():
        print("the solution tree changes nothing")
        return 1
    inst.solution_patch.write_text(patch, encoding="utf-8")
    print(f"wrote {inst.solution_patch.relative_to(Path.cwd())} ({len(patch.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
