"""Write the harness cases that come from the solutions, under tests/cases/.

    uv run python -m plugin.tools_dev.make_cases [project ...]

A gold case starts the project, writes every file the solution changes through write_file (up to
5 files, 60 KB per call), syncs, builds, runs the public tests and judges; the harness expects a
valid 1.0 verdict. ``wrong_judge_skipped.json`` is the arrays gold case without its judge step:
the harness expects an invalid verdict saying to call judge last.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from plugin.instances import all_instances, load_instance
from plugin.tools_dev.patches import changed_files_of

CASES = Path(__file__).resolve().parents[3] / "tests" / "cases"
MAX_FILES = 5
MAX_BYTES = 60 * 1024
SKIPPED_JUDGE_PROJECT = "arrays-numpy-2"


def write_steps(root: str, files: dict[str, str]) -> list[dict]:
    """write_file steps for ``files``, batched within the tool's limits."""
    steps: list[dict] = []
    batch: list[dict] = []
    size = 0
    for rel in sorted(files):
        item = {"path": f"{root}/{rel}", "content": files[rel]}
        cost = len(files[rel].encode("utf-8"))
        if batch and (len(batch) >= MAX_FILES or size + cost > MAX_BYTES):
            steps.append({"tool": "write_file", "arguments": {"files": batch}})
            batch, size = [], 0
        batch.append(item)
        size += cost
    if batch:
        steps.append({"tool": "write_file", "arguments": {"files": batch}})
    return steps


def gold_case(project: str) -> dict:
    inst = load_instance(project)
    root = f"dep-upgrade/{inst.id}"
    files = changed_files_of(inst)
    for rel in sorted(files):
        if rel != "pyproject.toml" and not rel.startswith(f"src/{inst.package}/"):
            raise ValueError(f"{inst.id}: solution.patch touches {rel}, which the task may not change")
    steps: list[dict] = [{"tool": "start_project", "arguments": {"project": inst.id}, "save_as": "start"}]
    steps += write_steps(root, files)
    steps += [
        {"tool": "sync", "arguments": {"project": inst.id}, "save_as": "sync"},
        {"tool": "run_build", "arguments": {"project": inst.id}, "save_as": "build"},
        {"tool": "run_tests", "arguments": {"project": inst.id, "tests": []}, "save_as": "tests"},
        {"tool": "judge", "arguments": {"project": inst.id}, "save_as": "judge"},
    ]
    return {
        "task": "upgrade-dependency",
        "arguments": {"project": inst.id},
        "steps": steps,
        "answer": f"Upgraded {inst.dependency} to {inst.target_version} and migrated {len(files) - 1} source file(s); build and tests pass.",
        "expect": {"valid": True, "score_min": 1.0},
    }


def judge_skipped_case(project: str) -> dict:
    case = gold_case(project)
    case["steps"] = [step for step in case["steps"] if step.get("tool") != "judge"]
    case["answer"] = "Upgraded and tested; done."
    case["expect"] = {"valid": False, "score_max": 0.0, "message_contains": "no judgement: call judge last"}
    return case


def main(argv: list[str]) -> int:
    names = argv or [inst.id for inst in all_instances()]
    CASES.mkdir(parents=True, exist_ok=True)
    for name in names:
        case = gold_case(name)
        path = CASES / f"gold_{name}.json"
        path.write_text(json.dumps(case, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {path.relative_to(CASES.parents[1])}: {len(case['steps'])} steps")
    if SKIPPED_JUDGE_PROJECT in names:
        case = judge_skipped_case(SKIPPED_JUDGE_PROJECT)
        path = CASES / "wrong_judge_skipped.json"
        path.write_text(json.dumps(case, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {path.relative_to(CASES.parents[1])}: {len(case['steps'])} steps")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
