"""Every scripted case, replayed the way NanoAgent runs a task (tests/replay.py): gold cases are valid
on every check, adversarial ones fail where their expectation says. Needs GitHub and PyPI."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from replay import meets, replay

CASES = sorted((Path(__file__).resolve().parent / "cases").glob("*.json"))


@pytest.mark.network
@pytest.mark.parametrize("case", CASES, ids=lambda path: path.stem)
def test_case(case: Path, tmp_path: Path):
    data = json.loads(case.read_text(encoding="utf-8"))
    verdict = replay(data, tmp_path)
    assert not meets(verdict, data["expect"]), verdict["message"]


def test_every_case_ends_in_submit_within_the_hosted_steps():
    for case in CASES:
        steps = [step for step in json.loads(case.read_text(encoding="utf-8"))["steps"] if "tool" in step]
        assert steps[-1]["tool"] == "submit", case.name
        assert len(steps) <= 6, case.name
