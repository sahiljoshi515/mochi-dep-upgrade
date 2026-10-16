"""Replay a scripted case the way NanoAgent runs a task, in this process and without NanoAgent: the
reference pinned in a scratch copy of the workspace, every tool call checked with verify_input and
verify_output, the submission built into the task's output class, and verify_task called twice
(the verdicts must agree). Used by the replay tests and for quick iteration:

    uv run python tests/replay.py tests/cases/<case>.json [--keep]
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from slimconfig import build_output, plain_output

import verifier
from contract import TASKS, TOOLS, Task, Tool
from plugin.__main__ import IMPLEMENTATIONS


def resolve(value, outputs):
    if isinstance(value, str) and value.startswith("$ref:"):
        node = outputs
        for part in value[5:].split("."):
            node = node[int(part)] if isinstance(node, list) else node[part]
        return node
    if isinstance(value, list):
        return [resolve(item, outputs) for item in value]
    if isinstance(value, dict):
        return {key: resolve(item, outputs) for key, item in value.items()}
    return value


def call(tool: Tool, arguments: dict, workspace: Path) -> dict:
    given, made = TOOLS[tool]
    value = build_output(arguments, given)
    checked = verifier.verify_input(tool.value, value)
    if not checked["valid"]:
        raise ValueError(f"input verification failed: {checked['message']}")
    output = IMPLEMENTATIONS[tool](value, workspace)
    checked = verifier.verify_output(tool.value, value, build_output(plain_output(output), made), str(workspace))
    if not checked["valid"]:
        raise RuntimeError(f"output verification failed: {checked['message']}")
    return plain_output(output)


def replay(case: dict, workspace: Path) -> dict:
    task = Task(case["task"])
    given, made = TASKS[task]
    arguments = build_output(case["arguments"], given)
    with tempfile.TemporaryDirectory(prefix="dep-upgrade-reference-") as scratch:
        shutil.copytree(workspace, scratch, dirs_exist_ok=True)
        reference = call(Tool.PIN_UPGRADE, case["arguments"], Path(scratch))
    outputs: dict = {}
    submitted = None
    for number, step in enumerate(case["steps"], 1):
        if "python" in step:
            exec(step["python"], {"workspace": workspace, "outputs": outputs, "json": json, "Path": Path})  # noqa: S102 - the case steps that act behind the tools' back
            continue
        arguments_given = resolve(step.get("arguments", {}), outputs)
        if step["tool"] == "submit":
            submitted = build_output(arguments_given, made)
            continue
        try:
            produced = call(Tool(step["tool"]), arguments_given, workspace)
            error = None
        except Exception as problem:  # noqa: BLE001 - the host feeds every failure back to the agent
            produced, error = None, problem
        if bool(error) != bool(step.get("expect_error", False)):
            raise AssertionError(f"step {number} {step['tool']}: expected error={step.get('expect_error', False)}, got {error!r}")
        if produced is not None and step.get("save_as"):
            outputs[step["save_as"]] = produced
    if submitted is None:
        raise AssertionError("the case never submits")
    pin = build_output(reference, TOOLS[Tool.PIN_UPGRADE][1])
    first = verifier.verify_task(task.value, arguments, submitted, pin, str(workspace))
    second = verifier.verify_task(task.value, arguments, submitted, pin, str(workspace))
    if json.dumps(first, sort_keys=True, default=str) != json.dumps(second, sort_keys=True, default=str):
        raise AssertionError("verify_task is not deterministic")
    return first


def meets(verdict: dict, expect: dict) -> list[str]:
    problems = []
    if "valid" in expect and verdict["valid"] != expect["valid"]:
        problems.append(f"valid={verdict['valid']} expected {expect['valid']}")
    if "score_min" in expect and verdict["score"] < expect["score_min"]:
        problems.append(f"score {verdict['score']} below {expect['score_min']}")
    if "score_max" in expect and verdict["score"] > expect["score_max"]:
        problems.append(f"score {verdict['score']} above {expect['score_max']}")
    if "message_contains" in expect and expect["message_contains"] not in verdict["message"]:
        problems.append(f"message {verdict['message']!r} lacks {expect['message_contains']!r}")
    return problems


def main(argv: list[str]) -> int:
    keep = "--keep" in argv
    status = 0
    for name in [arg for arg in argv if not arg.startswith("--")]:
        case = json.loads(Path(name).read_text(encoding="utf-8"))
        workspace = Path(tempfile.mkdtemp(prefix="dep-upgrade-ws-"))
        try:
            verdict = replay(case, workspace)
            problems = meets(verdict, case.get("expect", {}))
        except Exception as error:  # noqa: BLE001
            verdict, problems = {"valid": None, "score": None, "message": f"{type(error).__name__}: {error}"}, ["replay failed"]
        print(("OK   " if not problems else "FAIL ") + f"{Path(name).stem}: valid={verdict['valid']} score={verdict['score']} {verdict['message'][:240]}" + (f"  <- {problems}" if problems else ""), flush=True)
        if problems:
            status = 1
        if keep:
            print(f"     workspace kept: {workspace}")
        else:
            shutil.rmtree(workspace, ignore_errors=True)
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
