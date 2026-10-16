"""Tag each instance "hosted" or "local" from measured gold runs: the timings.json run_cases.py writes
for the gold cases run one at a time under the sandbox, from a cold cache.

    uv run python -m plugin.tools_dev.fit <timings.json> [--load <1-minute load average at the time>]

Hosted when the agent's tool time is at most 60 s, start_upgrade at most 45 s and judge at most 40 s,
each finishing in one call (no resume), and the gold takes at most six calls, submit included: a hosted
run has 180 s for everything, the model's six turns included.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from verifier import catalog

TOOL_SECONDS, START_SECONDS, JUDGE_SECONDS, TURNS = 60.0, 45.0, 40.0, 6


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("timings")
    parser.add_argument("--load", type=float, default=None)
    args = parser.parse_args(argv)
    timings = json.loads(Path(args.timings).read_text(encoding="utf-8"))
    path = catalog.CATALOG
    data = json.loads(path.read_text(encoding="utf-8"))
    for item in data["instances"]:
        run = timings.get(f"gold_{item['id']}")
        if run is None or not any(call["name"] == "judge" for call in run["tool_calls"]):
            continue  # not measured here, or the gold run did not get as far as judging
        calls = [call for call in run["tool_calls"] if call["name"] != "submit"]
        seconds = {name: round(sum(call["seconds"] for call in calls if call["name"] == name), 1) for name in {call["name"] for call in calls}}
        tool = round(sum(call["seconds"] for call in calls), 1)
        names = [call["name"] for call in run["tool_calls"]]
        single = names.count("start_upgrade") == 1 and names.count("judge") == 1
        turns = len(names)
        hosted = tool <= TOOL_SECONDS and seconds.get("start_upgrade", 0) <= START_SECONDS and seconds.get("judge", 0) <= JUDGE_SECONDS and single and turns <= TURNS
        item["timings"] = {"tool_seconds": tool, "by_tool": seconds, "single_calls": single, "turns": turns, "measured": "gold case, sandboxed, cold cache", "load_average": args.load}
        item["fit"] = "hosted" if hosted else "local"
        print(f"{item['id']}: {tool} s of tool time ({seconds}), start and judge once {single}, {turns} calls -> {item['fit']}")
    path.write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
