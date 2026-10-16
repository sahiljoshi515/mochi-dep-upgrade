"""Measure every instance's judged tests on this platform, and keep only what holds on all of them.

    uv run python -m plugin.tools_dev.platforms measure [<instance> ...] [--work DIR] [--out FILE]
    uv run python -m plugin.tools_dev.platforms apply <measurement.json> [<measurement.json> ...]

A test's id and outcome can depend on the platform: emcee parametrizes a test with a value computed
from ``np.longdouble``, which is 64-bit on Apple silicon and 80-bit on x86-64, so the test has another
id on each. ``measure`` runs the oracle's four defining cells here (``onboard``'s, from the catalog's
commits and locks), twice each, with the tests cut off from the network (sandbox-exec on macOS, bwrap
on Linux), and records how every judged test fares:

    R1 base src + base tests + old    R3 C src + base tests + new    public: passes both, both times
    R4 base src + C tests   + old     R5 C src + C tests   + new     hidden: passes both, both times

``apply`` keeps in each judged set only the tests that hold on every measured platform; the others move
to the instance's excluded lists with the reason (the platform, and how the test fares there), and the
platforms measured go into ``validated``.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

from plugin import envs
from plugin.common import Budget
from plugin.testing import run_suite
from plugin.tools_dev.onboard import DATA, RUNS, WORK, assemble, checkout, log, tarball
from verifier import catalog
from verifier.trees import tree_hash

PLATFORM_PREFIX = "platform-dependent: "


def platform_name() -> str:
    """``macos-arm64``, ``linux-x86_64``: the names data/pythons.json uses."""
    system = {"darwin": "macos"}.get(platform.system().lower(), platform.system().lower())
    machine = {"aarch64": "arm64", "amd64": "x86_64"}.get(platform.machine().lower(), platform.machine().lower())
    return f"{system}-{machine}"


def problem(name: str, before: list[str], after: list[str]) -> str | None:
    """Why a test does not hold on platform ``name``, from its outcomes in the before and after cells
    (both attempts each), or None when it passes all four."""
    outcomes = before + after
    if all(outcome == "passed" for outcome in outcomes):
        return None
    if all(outcome == "missing" for outcome in outcomes):
        return f"not collected on {name}"
    if len(set(before)) > 1 or len(set(after)) > 1:
        return f"flaky on {name}"
    if before[0] != "passed":
        return f"does not pass before the upgrade on {name} ({before[0]})"
    return f"does not pass after upstream's upgrade on {name} ({after[0]})"


def candidates(entry: dict, kind: str) -> list[str]:
    """The tests the oracle judged for ``kind`` (public or hidden): those judged now, and those a
    platform measured earlier set aside."""
    previous = [item["id"] for item in entry[kind].get("excluded", []) if item["reason"].startswith(PLATFORM_PREFIX)]
    return sorted(set(entry[kind]["ids"]) | set(previous))


def measure(entry: dict, work: Path, name: str) -> dict:
    """How every judged test of ``entry`` fares here: ``{"public": {id: problem or None}, "hidden": ...,
    "collected_only_here": [...]}``."""
    folder = work / entry["id"]
    folder.mkdir(parents=True, exist_ok=True)
    post_setup = entry.get("post_setup", {})
    base_dir, c_dir = folder / "base", folder / "c"
    base_files = checkout(tarball(entry["repo"], entry["base"]["commit"], work / "cache"), base_dir, post_setup)
    c_files = checkout(tarball(entry["repo"], entry["upstream"]["commit"], work / "cache"), c_dir, post_setup)
    if tree_hash(base_files.items()) != entry["base"]["tree_sha256"]:
        raise SystemExit(f"{entry['id']}: codeload served another base tree than the catalog validated")
    built = {}
    for env_name, which in (("old", "base"), ("new", "gold")):
        scratch = folder / f"env-{env_name}"
        note = envs.ensure_venv(entry, scratch, catalog.lock_text(entry, which), Budget(1800))
        if note:
            raise SystemExit(f"{entry['id']}: could not build the {env_name} environment: {note}")
        built[env_name] = scratch
    cells = {
        "R1": ("base", "base", "old", list(entry["test_dirs"])),
        "R3": ("c", "base", "new", list(entry["test_dirs"])),
        "R4": ("base", "c", "old", list(entry["hidden"]["targets"])),
        "R5": ("c", "c", "new", list(entry["hidden"]["targets"])),
    }
    runs: dict[str, list] = {}
    for cell, (src, tests, env_name, targets) in cells.items():
        runs[cell] = []
        for attempt in range(RUNS):
            tree = assemble(folder / "trees" / f"{cell}-{attempt}", base_dir, c_dir, base_files, c_files, src=src, tests=tests, recipe=entry)
            run = run_suite(tree, entry, built[env_name], rundir=folder / "runs" / f"{cell}-{attempt}", targets=targets, timeout=1200, isolate=True)
            if not run.report_read:
                raise SystemExit(f"{entry['id']}: {cell} produced no report on {name}: {run.tail[-8:]}")
            runs[cell].append(run)
            outcomes = list(run.outcomes.values())
            log(f"[{entry['id']}] {name} {cell}#{attempt}: collected {len(run.collected)}, passed {outcomes.count('passed')}, {run.seconds}s")

    def outcomes(cell: str, test: str) -> list[str]:
        return [run.outcome(test) for run in runs[cell]]

    known = set(entry["public"]["ids"]) | {item["id"] for item in entry["public"]["excluded"]}
    return {
        "public": {test: problem(name, outcomes("R1", test), outcomes("R3", test)) for test in candidates(entry, "public")},
        "hidden": {test: problem(name, outcomes("R4", test), outcomes("R5", test)) for test in candidates(entry, "hidden")},
        "collected_only_here": sorted(set(runs["R3"][0].collected) - known),
    }


def apply(measurements: list[dict], path: Path | None = None) -> int:
    """Pin the judged sets that hold on every measured platform into the catalog (``path``, by default
    the plugin's own)."""
    path = path or DATA / "catalog.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for entry in data["instances"]:
        found = [(item["platform"], item["instances"][entry["id"]]) for item in measurements if entry["id"] in item["instances"]]
        if not found:
            continue
        for kind in ("public", "hidden"):
            kept, moved = [], []
            for test in candidates(entry, kind):
                if any(test not in seen[kind] for _, seen in found):
                    raise SystemExit(f"{entry['id']}: {test} was not measured on every platform: measure again")
                reasons = [seen[kind][test] for _, seen in found if seen[kind][test]]
                if reasons:
                    moved.append({"id": test, "reason": PLATFORM_PREFIX + "; ".join(reasons)})
                else:
                    kept.append(test)
            if not kept:
                raise SystemExit(f"{entry['id']}: no {kind} test holds on every platform measured")
            entry[kind]["ids"] = kept
            excluded = [item for item in entry[kind].get("excluded", []) if not item["reason"].startswith(PLATFORM_PREFIX)]
            entry[kind]["excluded"] = moved + excluded
            if moved:
                log(f"[{entry['id']}] {kind}: {len(moved)} not judged: " + " | ".join(f"{item['id']}: {item['reason']}" for item in moved))
        if not any(item["test"] in entry["public"]["ids"] for item in entry.get("breaking", [])) and not entry["breakage"]["hidden"]:
            raise SystemExit(f"{entry['id']}: no breaking test is left to judge")
        entry["breaking"] = [item for item in entry.get("breaking", []) if item["test"] in entry["public"]["ids"]]
        platforms = sorted(set(entry["validated"]["platforms"]) | {name for name, _ in found})
        entry["validated"] = {**entry["validated"], "platforms": platforms, "platforms_at": max(item["measured_at"] for item in measurements)}
        only = {name: seen["collected_only_here"] for name, seen in found if seen["collected_only_here"]}
        if only:
            log(f"[{entry['id']}] collected on one platform only (never judged): {only}")
    path.write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    measuring = sub.add_parser("measure")
    measuring.add_argument("ids", nargs="*")
    measuring.add_argument("--work", default=str(WORK.parent / "platforms"))
    measuring.add_argument("--out", default=None)
    applying = sub.add_parser("apply")
    applying.add_argument("files", nargs="+")
    args = parser.parse_args(argv)
    if args.command == "apply":
        return apply([json.loads(Path(name).read_text(encoding="utf-8")) for name in args.files])
    name = platform_name()
    work = Path(args.work) / name
    entries = [entry for entry in catalog.load()["instances"] if not args.ids or entry["id"] in args.ids]
    result = {"platform": name, "measured_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "instances": {}}
    out = Path(args.out) if args.out else work / f"measurement-{name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        result["instances"][entry["id"]] = measure(entry, work, name)
        out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        seen = result["instances"][entry["id"]]
        bad = {kind: {test: reason for test, reason in seen[kind].items() if reason} for kind in ("public", "hidden")}
        log(f"[{entry['id']}] {name}: public problems {bad['public']}, hidden problems {bad['hidden']}, collected only here {seen['collected_only_here']}")
    log(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
