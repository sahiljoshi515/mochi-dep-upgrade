"""The page: ui/ holds only what NanoAgent serves, the lab's page check draws a report, and the checks
list draws verdicts of the synthetic instance (every check with its id, each failure with why and, where
the verdict has both, what was expected against what was found, each skipped check with what it needed)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import synthetic as s
from slimconfig import plain_output

import verifier

ROOT = Path(__file__).resolve().parents[1]
PAGE_CHECK = Path.home() / "mochi-dev" / "harness" / "page_check.sh"
KIT = Path.home() / "mochi-dev" / "rushlab" / "nanoagent" / "src" / "nanoagent" / "plugin" / "page" / "kit"
SHIM = Path.home() / "mochi-dev" / "harness" / "page" / "shim.mjs"
NEEDS_NODE = pytest.mark.skipif(shutil.which("node") is None or not PAGE_CHECK.is_file() or not KIT.is_dir() or not SHIM.is_file(), reason="needs node and the lab's page check")
DRAW = """
import "./shim.mjs";
import { readFileSync } from "node:fs";
const renderers = (await import("./renderers.js")).default;
const value = JSON.parse(readFileSync("./sample.json", "utf8"));
const verdict = JSON.parse(readFileSync("./verdict.json", "utf8"));
console.log(renderers.UpgradeReportOutput(value, { task: {}, verdict, send: () => {} }).textContent);
"""


def test_ui_holds_only_the_renderers() -> None:
    assert sorted(path.name for path in (ROOT / "ui").iterdir()) == ["renderers.css", "renderers.js"]


@NEEDS_NODE
def test_the_page_check_draws_a_report(tmp_path: Path) -> None:
    sample = tmp_path / "report.json"
    sample.write_text(json.dumps(plain_output(s.submission())), encoding="utf-8")
    done = subprocess.run(["bash", str(PAGE_CHECK), str(ROOT), f"UpgradeReportOutput={sample}"], capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == 0 and "render UpgradeReportOutput: OK" in done.stdout, done.stdout + done.stderr


def synthetic_verdict(tmp_path: Path, demo: dict, fault: str) -> dict:
    root = s.started_workspace(tmp_path, demo)
    if fault != "no judgement":
        s.write_project(root, s.UPGRADED)
        override = {"lock": {"ok": False, "tail": ["no solution found"]}} if fault == "unresolved lock" else {}
        s.judged(root, demo, **override)
    return verifier.verify_task("upgrade-dependency", s.arguments(), s.submission(), s.pin(demo), str(tmp_path))


@NEEDS_NODE
@pytest.mark.parametrize("fault", ["none", "no judgement", "unresolved lock"])
def test_the_checks_list_draws_each_verdict(tmp_path: Path, demo: dict, fault: str) -> None:
    verdict = synthetic_verdict(tmp_path / "work", demo, fault)
    page = tmp_path / "page"
    shutil.copytree(KIT, page / "kit")
    for file in ("renderers.js", "renderers.css"):
        shutil.copy(ROOT / "ui" / file, page / file)
    shutil.copy(SHIM, page / "shim.mjs")
    (page / "sample.json").write_text(json.dumps(plain_output(s.submission())), encoding="utf-8")
    (page / "verdict.json").write_text(json.dumps(verdict), encoding="utf-8")
    (page / "check.mjs").write_text(DRAW, encoding="utf-8")
    done = subprocess.run(["node", "check.mjs"], cwd=page, capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    entries = verdict["details"]["constraints"]
    held = sum(entry["ok"] is True for entry in entries)
    words = [f"Checks: {held} of {len(entries)} hold", *(entry["constraint"] for entry in entries), *(entry["id"] for entry in entries)]
    words += [entry["message"] for entry in entries if entry["ok"] is not True]
    for word in words:
        assert word in done.stdout, (word, done.stdout)
    shows_values = any(entry["ok"] is False and None not in (entry["expected"], entry["actual"]) for entry in entries)
    assert ("Expected: " in done.stdout) == shows_values
    assert verdict["valid"] is (fault == "none")
