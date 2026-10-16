"""Judged sets that hold on every platform (tools_dev/platforms.py): how a test's outcomes on one platform
become a reason, and how measurements from several platforms pin the judged sets, the excluded lists
with their reasons, and the platforms validated."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from plugin.project import excluded_first
from plugin.tools_dev.platforms import apply, problem


def test_how_a_test_fares_on_a_platform():
    assert problem("linux-x86_64", ["passed", "passed"], ["passed", "passed"]) is None
    assert problem("linux-x86_64", ["missing", "missing"], ["missing", "missing"]) == "not collected on linux-x86_64"
    assert problem("linux-x86_64", ["passed", "failed"], ["passed", "passed"]) == "flaky on linux-x86_64"
    assert problem("linux-x86_64", ["failed", "failed"], ["passed", "passed"]) == "does not pass before the upgrade on linux-x86_64 (failed)"
    assert problem("linux-x86_64", ["passed", "passed"], ["error", "error"]) == "does not pass after upstream's upgrade on linux-x86_64 (error)"


def entry() -> dict:
    return {
        "id": "demo",
        "public": {"ids": ["t.py::a", "t.py::b", "t.py::c"], "excluded": [{"id": "t.py::z", "reason": "flaky: outcomes differ between identical runs"}]},
        "hidden": {"commit": "1" * 40, "files": {}, "targets": ["h.py"], "ids": ["h.py::one", "h.py::two"]},
        "breaking": [{"test": "t.py::a", "error": "AttributeError"}, {"test": "t.py::b", "error": "TypeError"}],
        "breakage": {"public": 2, "hidden": 1},
        "validated": {"platforms": ["macos-arm64"], "at": "2026-10-15T00:00:00Z"},
    }


def measurement(name: str, public: dict, hidden: dict) -> dict:
    return {"platform": name, "measured_at": "2026-10-17T00:00:00Z", "instances": {"demo": {"public": public, "hidden": hidden, "collected_only_here": []}}}


MAC = measurement("macos-arm64", {"t.py::a": None, "t.py::b": None, "t.py::c": None}, {"h.py::one": None, "h.py::two": None})
LINUX = measurement(
    "linux-x86_64",
    {"t.py::a": None, "t.py::b": "not collected on linux-x86_64", "t.py::c": None},
    {"h.py::one": None, "h.py::two": "does not pass after upstream's upgrade on linux-x86_64 (failed)"},
)


def pinned(tmp_path: Path, *measurements: dict, item: dict | None = None) -> dict:
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({"version": 1, "instances": [item or entry()]}))
    apply(list(measurements), path)
    return json.loads(path.read_text())["instances"][0]


def test_only_what_holds_on_every_platform_is_judged(tmp_path: Path):
    item = pinned(tmp_path, MAC, LINUX)
    assert item["public"]["ids"] == ["t.py::a", "t.py::c"]
    assert item["public"]["excluded"] == [
        {"id": "t.py::b", "reason": "platform-dependent: not collected on linux-x86_64"},
        {"id": "t.py::z", "reason": "flaky: outcomes differ between identical runs"},
    ]
    assert item["hidden"]["ids"] == ["h.py::one"]
    assert item["hidden"]["excluded"] == [{"id": "h.py::two", "reason": "platform-dependent: does not pass after upstream's upgrade on linux-x86_64 (failed)"}]
    assert item["validated"]["platforms"] == ["linux-x86_64", "macos-arm64"]
    assert [entry["test"] for entry in item["breaking"]] == ["t.py::a"]


def test_pinning_again_gives_the_same_entry(tmp_path: Path):
    once = pinned(tmp_path, MAC, LINUX)
    assert pinned(tmp_path, MAC, LINUX, item=once) == once


def test_a_test_measured_fine_everywhere_again_is_judged_again(tmp_path: Path):
    once = pinned(tmp_path, MAC, LINUX)
    fixed = measurement("linux-x86_64", {"t.py::a": None, "t.py::b": None, "t.py::c": None}, {"h.py::one": None, "h.py::two": None})
    again = pinned(tmp_path, MAC, fixed, item=once)
    assert again["public"]["ids"] == ["t.py::a", "t.py::b", "t.py::c"] and again["hidden"]["ids"] == ["h.py::one", "h.py::two"]


def test_a_test_not_measured_everywhere_stops_the_pinning(tmp_path: Path):
    partial = measurement("linux-x86_64", {"t.py::a": None, "t.py::c": None}, {"h.py::one": None, "h.py::two": None})
    with pytest.raises(SystemExit, match="not measured on every platform"):
        pinned(tmp_path, MAC, partial)


def test_a_set_left_empty_stops_the_pinning(tmp_path: Path):
    broken = measurement("linux-x86_64", {"t.py::a": None, "t.py::b": None, "t.py::c": None}, {"h.py::one": "not collected on linux-x86_64", "h.py::two": "not collected on linux-x86_64"})
    with pytest.raises(SystemExit, match="no hidden test holds"):
        pinned(tmp_path, MAC, broken)


def test_the_start_lists_platform_dependent_exclusions_first():
    item = {"public": {"excluded": [{"id": "t.py::z", "reason": "flaky: outcomes differ between identical runs"}, {"id": "t.py::b", "reason": "platform-dependent: not collected on linux-x86_64"}]}}
    assert [entry["id"] for entry in excluded_first(item)] == ["t.py::b", "t.py::z"]
