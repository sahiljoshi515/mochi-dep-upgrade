"""Build-time oracle: turn a recipe (a real upstream commit C that upgraded one dependency) into a
validated catalog entry, or say why it does not qualify.

    uv run python -m plugin.tools_dev.onboard <recipe id> [<recipe id> ...] [--work DIR] [--write]

Recipes live in ``tools_dev/recipes.json``. For each: fetch the parent of C (the base) and C from
codeload; read both specs; resolve the pre-upgrade lock (base spec) and the validated post-upgrade
lock (C's spec) as of one resolution date, with the test requirements; check that the sync path
(C's spec with every base pin held except what moves) reproduces the post-upgrade lock; read PyPI's
files for the target; then run the oracle matrix, every cell twice:

    R1 base src + base tests + old    R2 base src + base tests + new    R3 C src + base tests + new
    R4 base src + C tests   + old     R5 C src    + C tests   + new     R6 base src + C tests + new

Public tests: base tests passing in R1 and R3, both times (at most 20% excluded). Hidden tests:
tests in the test files C changed, passing in R4 and R5 both times (at least one). Breakage: some
public test failing in R2 or hidden test failing in R6 (else a bare bump would do). Limits come
from C's own change to the editable files; shim patterns that upstream's own added lines match are
dropped. With --write, the entry and its locks go into src/plugin/data/.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from plugin import envs, fetch
from plugin.common import Budget, sha256_bytes
from plugin.spec import read as read_spec
from plugin.testing import copy_tree, run_suite
from verifier import catalog
from verifier.locks import read_lock, versions_of
from verifier.trees import added_lines, counts, matches_any, text_lines, tree_entries, tree_hash
from verifier.versions import admits, canonical_name, parse_requirement

HERE = Path(__file__).resolve().parent
RECIPES = HERE / "recipes.json"
DATA = Path(catalog.DATA)
WORK = Path.home() / "mochi-dev" / "runs" / "dep-upgrade" / "build"
MAX_FILES = 2000
MAX_BYTES = 20 * 1024 * 1024
MAX_EXCLUDED_SHARE = 0.20
RUNS = 2
GENERIC_FORBIDDEN = [
    r"\bwarnings\.(?:filterwarnings|simplefilter|catch_warnings|resetwarnings)\b",
    r"\bsys\.modules\b",
    r"\bimportlib\.reload\b",
    r"\b__import__\(",
    r"PYTEST_CURRENT_TEST",
    r"""["']pytest["']\s+in\s+sys\.modules""",
    r"\bsys\.argv\b",
    r"\bpkg_resources\b",
]


def library_forbidden(recipe: dict) -> list[str]:
    names = "|".join(recipe["import_names"])
    dist = recipe["dependency"]
    patterns = [
        rf"\bsetattr\(\s*(?:{names})\b",
        rf"^\s*(?:{names})\.[A-Za-z_][A-Za-z0-9_.]*\s*=(?!=)",
        rf"\b(?:{names})\.__version__\b",
        rf"""\bversion\(\s*["']{dist}["']\s*\)""",
    ]
    if canonical_name(dist) == "pydantic":
        patterns.append(r"\bpydantic\.v1\b")
    return patterns + recipe.get("forbidden_extra", [])


def log(message: str) -> None:
    print(message, flush=True)


def gh_commit(repo: str, commit: str) -> dict:
    out = subprocess.run(["gh", "api", f"repos/{repo}/commits/{commit}"], capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    return {
        "sha": data["sha"],
        "parents": [parent["sha"] for parent in data["parents"]],
        "date": data["commit"]["committer"]["date"],
        "message": data["commit"]["message"].splitlines()[0][:200],
    }


def tarball(repo: str, commit: str, cache: Path) -> bytes:
    path = cache / f"{repo.replace('/', '__')}-{commit}.tar.gz"
    if path.is_file():
        return path.read_bytes()
    data = fetch.codeload(repo, commit)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def checkout(data: bytes, dest: Path) -> dict[str, str]:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    fetch.unpack(data, dest, keep=counts)
    return dict(tree_entries(dest))


def tests_in(rel: str, test_dirs: list[str]) -> bool:
    return any(rel == folder or rel.startswith(folder.rstrip("/") + "/") for folder in test_dirs)


def assemble(dest: Path, base: Path, upstream: Path, base_files: dict, c_files: dict, *, src: str, tests: str, recipe: dict) -> Path:
    """A tree: the base checkout, with C's version of the source and/or of the tests overlaid."""
    tree = copy_tree(base, dest)
    pick = []
    if src == "c":
        pick.append(lambda rel: matches_any(rel, recipe["source_globs"]))
    if tests == "c":
        pick.append(lambda rel: tests_in(rel, recipe["test_dirs"]))
    for chosen in pick:
        for rel in sorted(set(base_files) | set(c_files)):
            if not chosen(rel):
                continue
            if rel in c_files:
                (tree / rel).parent.mkdir(parents=True, exist_ok=True)
                (tree / rel).write_bytes((upstream / rel).read_bytes())
            elif (tree / rel).exists():
                (tree / rel).unlink()
    return tree


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def onboard(recipe: dict, work: Path) -> dict:
    """The catalog entry for ``recipe`` (raises SystemExit with the reason when it does not qualify)."""
    folder = work / recipe["id"]
    folder.mkdir(parents=True, exist_ok=True)
    scratch = folder / "scratch"
    scratch.mkdir(exist_ok=True)
    commit = gh_commit(recipe["repo"], recipe["upstream_commit"])
    if len(commit["parents"]) != 1:
        raise SystemExit(f"{recipe['id']}: C is a merge commit")
    base_commit = commit["parents"][0]
    log(f"[{recipe['id']}] C={commit['sha'][:12]} base={base_commit[:12]} date={commit['date']}")
    base_data = tarball(recipe["repo"], base_commit, work / "cache")
    c_data = tarball(recipe["repo"], commit["sha"], work / "cache")
    base_dir, c_dir = folder / "base", folder / "c"
    base_files, c_files = checkout(base_data, base_dir), checkout(c_data, c_dir)
    size = sum((base_dir / rel).stat().st_size for rel in base_files)
    if len(base_files) > MAX_FILES or size > MAX_BYTES:
        raise SystemExit(f"{recipe['id']}: {len(base_files)} files, {size} bytes: over the limits")

    spec = recipe["spec"]
    base_spec, _ = read_spec(spec["kind"], (base_dir / spec["file"]).read_bytes().decode("utf-8"), name=spec["file"])
    c_spec, _ = read_spec(spec["kind"], (c_dir / spec["file"]).read_bytes().decode("utf-8"), name=spec["file"])
    entry_stub = {"dependency": recipe["dependency"], "python": recipe["python"], "test_requirements": recipe["test_requirements"]}
    resolution = recipe.get("resolution_date") or iso(datetime.fromisoformat(commit["date"]) + timedelta(days=1))
    entry_stub["resolution_date"] = resolution
    budget = Budget(600)
    # A spec that already admits the new version is held below it for the pre-upgrade lock (base_constraints).
    done, base_lock = envs.compile_lock(entry_stub, base_spec, scratch, constraints=recipe.get("base_constraints"), timeout=budget.slice(300))
    if not base_lock:
        raise SystemExit(f"{recipe['id']}: the base spec does not resolve: {done.tail[-5:]}")
    done, gold_lock = envs.compile_lock(entry_stub, c_spec, scratch, constraints=None, timeout=budget.slice(300))
    if not gold_lock:
        raise SystemExit(f"{recipe['id']}: C's spec does not resolve: {done.tail[-5:]}")
    dep = canonical_name(recipe["dependency"])
    base_versions, gold_versions = versions_of(read_lock(base_lock)), versions_of(read_lock(gold_lock))
    old, new = base_versions.get(dep, []), gold_versions.get(dep, [])
    if len(old) != 1 or len(new) != 1 or old == new:
        raise SystemExit(f"{recipe['id']}: the dependency locks {old} before and {new} after")
    from_version, target_version = old[0], new[0]
    collateral = sorted(name for name in set(base_versions) & set(gold_versions) if name != dep and base_versions[name] != gold_versions[name])
    allowed_new = sorted(set(gold_versions) - set(base_versions))
    log(f"[{recipe['id']}] {recipe['dependency']} {from_version} -> {target_version}; collateral {collateral}; new {allowed_new}")

    entry = {
        "id": recipe["id"],
        "title": recipe["title"],
        "repo": recipe["repo"],
        "license": recipe["license"],
        "base": {"commit": base_commit, "tree_sha256": tree_hash(base_files.items()), "files": len(base_files), "bytes": size},
        "upstream": {"commit": commit["sha"], "date": commit["date"], "message": commit["message"], "url": f"https://github.com/{recipe['repo']}/commit/{commit['sha']}"},
        "dependency": recipe["dependency"],
        "import_names": recipe["import_names"],
        "from_version": from_version,
        "target_version": target_version,
        "resolution_date": resolution,
        "python": recipe["python"],
        "spec": {
            "kind": spec["kind"],
            "file": spec["file"],
            "base_requirement": envs.dependency_requirement(entry_stub, base_spec),
            "upstream_requirement": envs.dependency_requirement(entry_stub, c_spec),
            "must_exclude_old": not admits(parse_requirement(envs.dependency_requirement(entry_stub, c_spec)).specifier, from_version),
        },
        "source_globs": recipe["source_globs"],
        "test_dirs": recipe["test_dirs"],
        "test_requirements": recipe["test_requirements"],
        "pytest_args": recipe.get("pytest_args", []),
        "path_entries": recipe.get("path_entries", ["."]),
        "env": recipe.get("env", {}),
        "allowed_collateral": collateral,
        "allowed_new": allowed_new,
        "locks": {
            "base": f"locks/{recipe['id']}.base.txt",
            "base_sha256": sha256_bytes(base_lock.encode("utf-8")),
            "gold": f"locks/{recipe['id']}.gold.txt",
            "gold_sha256": sha256_bytes(gold_lock.encode("utf-8")),
        },
    }
    # The locks must be on disk for constraints_for (it reads the base lock through the catalog).
    staging = folder / "data"
    (staging / "locks").mkdir(parents=True, exist_ok=True)
    (staging / entry["locks"]["base"]).write_text(base_lock, encoding="utf-8")
    (staging / entry["locks"]["gold"]).write_text(gold_lock, encoding="utf-8")
    catalog.DATA = staging  # read this build's locks while onboarding
    held = envs.constraints_for(entry)
    done, synced = envs.compile_lock(entry, c_spec, scratch, constraints=held, timeout=budget.slice(300))
    if synced != gold_lock:
        raise SystemExit(f"{recipe['id']}: the sync path does not reproduce the post-upgrade lock: {done.tail[-5:]}")
    release = fetch.pypi_release(recipe["dependency"], target_version)
    if release["yanked"] or not release["files"]:
        raise SystemExit(f"{recipe['id']}: PyPI serves no usable files for {target_version}")
    entry["target_files"] = release["files"]

    # Environments for the matrix.
    envs_built = {}
    for name, lock in (("old", base_lock), ("new", gold_lock)):
        cell_scratch = folder / f"env-{name}"
        note = envs.ensure_venv(entry, cell_scratch, lock, Budget(900))
        if note:
            raise SystemExit(f"{recipe['id']}: could not build the {name} environment in time: {note}")
        envs_built[name] = cell_scratch
    cells = {
        "R1": ("base", "base", "old"),
        "R2": ("base", "base", "new"),
        "R3": ("c", "base", "new"),
        "R4": ("base", "c", "old"),
        "R5": ("c", "c", "new"),
        "R6": ("base", "c", "new"),
    }
    results: dict[str, list] = {}
    for cell, (src, tests, env_name) in cells.items():
        results[cell] = []
        for attempt in range(RUNS):
            tree = assemble(folder / "trees" / f"{cell}-{attempt}", base_dir, c_dir, base_files, c_files, src=src, tests=tests, recipe=entry)
            run = run_suite(tree, entry, envs_built[env_name], rundir=folder / "runs" / f"{cell}-{attempt}", targets=list(entry["test_dirs"]), timeout=600, isolate=True)
            if not run.report_read:
                raise SystemExit(f"{recipe['id']}: {cell} produced no report: {run.tail[-8:]}")
            results[cell].append(run)
            outcomes = list(run.outcomes.values())
            log(f"[{recipe['id']}] {cell}#{attempt}: collected {len(run.collected)}, passed {outcomes.count('passed')}, failed {outcomes.count('failed')}, errors {outcomes.count('error')}, {run.seconds}s")

    def passed_all(cell: str, test: str) -> bool:
        return all(run.outcome(test) == "passed" for run in results[cell])

    def stable(cell: str, test: str) -> bool:
        return len({run.outcome(test) for run in results[cell]}) == 1

    collected = sorted(set(results["R1"][0].collected))
    public = [test for test in collected if passed_all("R1", test) and passed_all("R3", test)]
    excluded = []
    for test in collected:
        if test in public:
            continue
        if not (stable("R1", test) and stable("R3", test)):
            reason = "flaky: outcomes differ between identical runs"
        elif not passed_all("R1", test):
            reason = f"does not pass before the upgrade ({results['R1'][0].outcome(test)})"
        else:
            reason = f"does not pass after upstream's upgrade ({results['R3'][0].outcome(test)}): it tests the old version's behaviour"
        excluded.append({"id": test, "reason": reason})
    if not public or len(excluded) > MAX_EXCLUDED_SHARE * len(collected):
        raise SystemExit(f"{recipe['id']}: {len(excluded)} of {len(collected)} base tests excluded (at most {MAX_EXCLUDED_SHARE:.0%})")

    changed_tests = sorted(rel for rel in c_files if tests_in(rel, entry["test_dirs"]) and base_files.get(rel) != c_files[rel])
    test_files = [rel for rel in changed_tests if rel.endswith(".py")]
    hidden = sorted(
        test
        for test in set(results["R5"][0].collected)
        if test.split("::", 1)[0] in test_files and passed_all("R4", test) and passed_all("R5", test)
    )
    if not hidden:
        raise SystemExit(f"{recipe['id']}: no hidden test: none of C's changed test files has a test passing in R4 and R5")
    breaking_public = [test for test in public if not passed_all("R2", test)]
    breaking_hidden = [test for test in hidden if not passed_all("R6", test)]
    if not breaking_public and not breaking_hidden:
        raise SystemExit(f"{recipe['id']}: nothing breaks on the new version: a bare version bump would pass")
    entry["public"] = {"ids": public, "excluded": excluded}
    entry["hidden"] = {
        "commit": commit["sha"],
        "files": {rel: c_files[rel] for rel in changed_tests},
        "targets": sorted({test.split("::", 1)[0] for test in hidden}),
        "ids": hidden,
    }
    r2 = results["R2"][0]
    entry["breaking"] = [{"test": test, "error": (r2.messages.get(test) or r2.outcome(test))[:200]} for test in breaking_public[:10]]
    entry["breakage"] = {"public": len(breaking_public), "hidden": len(breaking_hidden)}

    # Upstream's own change to the editable files: the gold, the limits and the shim patterns. In the
    # spec file only the requirements count (upstream may also have touched metadata the task keeps).
    gold_files = sorted(rel for rel in set(base_files) | set(c_files) if matches_any(rel, entry["source_globs"]) and base_files.get(rel) != c_files.get(rel))
    gold_added = []
    for rel in gold_files:
        before = text_lines((base_dir / rel).read_bytes()) if rel in base_files else []
        after = text_lines((c_dir / rel).read_bytes()) if rel in c_files else []
        gold_added += added_lines(before, after)
    if base_spec != c_spec:
        gold_files = sorted([*gold_files, spec["file"]])
        gold_added += [item for item in c_spec if item not in base_spec]
    new_files = sum(1 for rel in gold_files if rel not in base_files)
    entry["limits"] = {
        "max_changed_files": max(5, 2 * len(gold_files)),
        "max_new_files": max(2, new_files),
        "max_added_lines": max(150, 3 * len(gold_added)),
    }
    patterns = GENERIC_FORBIDDEN + library_forbidden(recipe)
    entry["forbidden"] = [pattern for pattern in patterns if not any(re.search(pattern, line) for line in gold_added)]
    entry["gold"] = {"files": gold_files, "added_lines": len(gold_added)}
    entry["fit"] = "local"
    entry["timings"] = {}
    entry["validated"] = {"platforms": ["macos-arm64"], "at": iso(datetime.now(UTC))}
    entry["notes"] = recipe.get("notes", "")
    summary = {cell: [{"collected": len(run.collected), "passed": list(run.outcomes.values()).count("passed"), "seconds": run.seconds} for run in runs] for cell, runs in results.items()}
    (folder / "oracle.json").write_text(json.dumps({"entry": entry, "cells": summary}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    log(f"[{recipe['id']}] OK: {len(public)} public ({len(excluded)} excluded), {len(hidden)} hidden, breaks {len(breaking_public)} public / {len(breaking_hidden)} hidden; gold {len(gold_files)} files +{len(gold_added)} lines")
    return entry


def write(entry: dict, work: Path) -> None:
    """Merge ``entry`` into src/plugin/data/catalog.json and copy its locks beside it."""
    staging = work / entry["id"] / "data"
    for which in ("base", "gold"):
        target = DATA / entry["locks"][which]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((staging / entry["locks"][which]).read_bytes())
    path = DATA / "catalog.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"version": 1, "instances": []}
    data["instances"] = [item for item in data["instances"] if item["id"] != entry["id"]] + [entry]
    data["instances"].sort(key=lambda item: item["id"])
    path.write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ids", nargs="+")
    parser.add_argument("--work", default=str(WORK))
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    recipes = {item["id"]: item for item in json.loads(RECIPES.read_text(encoding="utf-8"))}
    failures = 0
    for recipe_id in args.ids:
        try:
            entry = onboard(recipes[recipe_id], Path(args.work))
        except SystemExit as reason:
            log(f"REJECTED {reason}")
            failures += 1
            continue
        if args.write:
            catalog.DATA = DATA
            write(entry, Path(args.work))
            log(f"[{recipe_id}] written to the catalog")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
