"""The judge: the trusted, final look at an instance, in stages that resume across calls.

Stages: diff (every change against the pristine record) -> lock (the spec as it stands, resolved
with everything else held) -> install (exactly that lock, then ``uv pip check``) -> build (the
wheel, and the requirements it declares) -> public (the repository's tests; failures rerun once)
-> hidden (upstream's post-upgrade test files, fetched from GitHub at the upgrade commit and
checked against the catalog, overlaid on a scratch copy and run) -> probe (what importing the
project does to the warnings filters, the import hooks and the dependency, against a clean
interpreter) -> scan (shims in the code the change adds, read with ``verifier.shims``). Each stage's result goes into ``.judge/progress.json`` under the hash of the tree it judged;
a call that runs out of budget returns ``complete: false`` and the next call carries on. When every
stage is done the judge writes ``.judge/judgement.json`` (``complete: true``) and returns counts and
the changed files, nothing about the hidden tests. Builds and test runs happen outside the workspace.
"""

from __future__ import annotations

import re
import shutil
import time
import zipfile
from pathlib import Path

from contract import JudgeOutput, UpgradeInput
from plugin import envs, fetch, probe, shims
from plugin.common import (
    JUDGE_DIR,
    Budget,
    ToolError,
    check_workspace_sizes,
    load_progress,
    run,
    save_progress,
    scratch_for,
    scrub,
    sha256_bytes,
    uv,
    write_json,
)
from plugin.project import JUDGEMENT, LOCK, ready_root, setup_token
from plugin.sync import relock, spec_requirements
from plugin.testing import copy_tree, judged, run_suite
from verifier import catalog
from verifier.locks import read_lock
from verifier.shims import added_lines_by_file, pristine_manifest, recorded_problems, scan
from verifier.trees import changes, matches_any, text_lines, tree_entries, tree_hash, unified
from verifier.versions import canonical_name

DIFF = "diff.patch"
BUILD_TIMEOUT = 90.0
TESTS_TIMEOUT = 120.0
MAX_LISTED = 50


def requires_dist(wheel: Path) -> list[str]:
    """The wheel's unconditional Requires-Dist lines (extras left out)."""
    with zipfile.ZipFile(wheel) as archive:
        name = next((item for item in archive.namelist() if item.endswith(".dist-info/METADATA")), None)
        if name is None:
            return []
        text = archive.read(name).decode("utf-8", errors="replace")
    found = []
    for line in text.split("\n\n", 1)[0].splitlines():
        if line.startswith("Requires-Dist:"):
            value = line.split(":", 1)[1].strip()
            if not re.search(r"\bextra\s*==", value):
                found.append(value)
    return found


def _tests_record(kind: str, run_result, ids: list[str], *, reruns: list[str] | None = None, extra: dict | None = None) -> dict:
    failed, missing = judged(run_result, ids)
    record = {
        "ran": True,
        "ok": run_result.report_read and not run_result.timed_out and not failed and not missing,
        "ids_sha256": catalog.ids_sha256(ids),
        "passed": sum(1 for test in ids if run_result.outcome(test) == "passed"),
        "failed": failed[:MAX_LISTED],
        "failed_count": len(failed),
        "missing": missing[:MAX_LISTED],
        "missing_count": len(missing),
        "exit_status": run_result.exit_status,
        "seconds": run_result.seconds,
        "reruns": reruns or [],
    }
    if not record["ok"]:
        record["tail"] = run_result.tail[-20:]
    record.update(extra or {})
    return record


def hidden_files(entry: dict, scratch: Path) -> dict[str, bytes]:
    """Upstream's post-upgrade test files, from GitHub at the upgrade commit, each checked against
    the sha256 the catalog validated."""
    commit = entry["hidden"]["commit"]
    cache = scratch / "upstream" / f"{commit}.tar.gz"
    if cache.is_file():
        data = cache.read_bytes()
    else:
        data = fetch.codeload(entry["repo"], commit)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(data)
    wanted = entry["hidden"]["files"]
    found = {rel: content for rel, content in fetch.members(data) if rel in wanted}
    for rel, sha in wanted.items():
        if rel not in found or sha256_bytes(found[rel]) != sha:
            raise ToolError("GitHub served other hidden test files than the ones validated")
    return found


def judge(given: UpgradeInput, workspace: Path, *, budget: Budget | None = None) -> JudgeOutput:
    budget = budget or Budget()
    root, entry = ready_root(workspace, given.instance.value)
    scratch = scratch_for(workspace, entry["id"])
    dependency = entry["dependency"]
    manifest = pristine_manifest(root)
    if manifest is None or tree_hash(manifest["files"].items()) != entry["base"]["tree_sha256"]:
        raise ToolError("the pristine record is missing or altered: start_upgrade again")
    entries = tree_entries(root)
    tree_now = tree_hash(entries)
    progress = load_progress(root)
    state = progress.get("judge") if isinstance(progress.get("judge"), dict) else None
    if not state or state.get("tree") != tree_now or not isinstance(state.get("stages"), dict):
        state = {"tree": tree_now, "stages": {}, "unstable": False}
    stages: dict = state["stages"]

    def persist() -> None:
        # A stage that changed the tree (code run by the tests writing files) marks the judgement.
        if tree_hash(tree_entries(root)) != tree_now:
            state["unstable"] = True
        progress["judge"] = state
        save_progress(root, progress)

    def output(*, recorded: bool, complete: bool, next_step: str) -> JudgeOutput:
        public = stages.get("public", {})
        return JudgeOutput(
            recorded=recorded,
            complete=complete,
            next=next_step,
            changed_files=[item["path"] for item in stages.get("diff", {}).get("changed", [])],
            requirement=stages.get("spec", {}).get("requirement", ""),
            locked_version=stages.get("lock", {}).get("dependency_version", ""),
            installed_version=stages.get("install", {}).get("installed", {}).get(canonical_name(dependency), ""),
            build_ok=bool(stages.get("build", {}).get("ok", False)),
            public_passed=int(public.get("passed", 0)),
            public_failed=int(public.get("failed_count", 0)) + int(public.get("missing_count", 0)),
            violations=[*stages.get("scan", {}).get("shims", []), *(f"importing the project {finding}" for finding in stages.get("probe", {}).get("unexpected", []))],
            seconds=round(budget.spent, 2),
        )

    def pause(note: str) -> JudgeOutput:
        persist()
        return output(recorded=False, complete=False, next_step=f"call judge again to continue: {note}")

    if "diff" not in stages:
        changed = changes(manifest["files"], entries)
        added = added_lines_by_file(root, changed)
        stages["diff"] = {"changed": [{**item, "added_lines": len(added.get(item["path"], []))} for item in changed]}
        try:
            requirements = spec_requirements(root, entry)
            stages["spec"] = {"ok": True, "requirements": requirements, "requirement": envs.dependency_requirement(entry, requirements)}
        except ToolError as error:
            stages["spec"] = {"ok": False, "requirements": [], "requirement": "", "error": str(error)}
        persist()
    changed = [{key: item[key] for key in ("path", "status", "sha256")} for item in stages["diff"]["changed"]]

    if "lock" not in stages:
        if not stages["spec"]["ok"]:
            stages["lock"] = {"ok": False, "tail": [stages["spec"]["error"]]}
        else:
            if not budget.allows(15):
                return pause("locking is next")
            text, tail, timed_out = relock(root, entry, scratch, budget)
            if timed_out:
                return pause("locking did not finish")
            if not text:
                stages["lock"] = {"ok": False, "tail": tail[-20:]}
            else:
                (root / JUDGE_DIR / LOCK).write_text(text, encoding="utf-8")
                pins = read_lock(text).get(canonical_name(dependency), [])
                stages["lock"] = {"ok": True, "sha256": sha256_bytes(text.encode("utf-8")), "dependency_version": ",".join(sorted({pin["version"] for pin in pins}))}
        persist()
    lock_ok = stages["lock"]["ok"]
    skipped = "the spec did not resolve"

    if "install" not in stages:
        if not lock_ok:
            stages["install"] = {"ok": False, "skipped": skipped, "installed": {}, "pip_check": {"ok": False}}
        else:
            lock_text = (root / JUDGE_DIR / LOCK).read_text(encoding="utf-8")
            note = envs.ensure_venv(entry, scratch, lock_text, budget)
            if note:
                return pause(note)
            installed = envs.installed_versions(scratch, sorted(read_lock(lock_text)))
            check = envs.pip_check(scratch, budget)
            stages["install"] = {"ok": True, "installed": installed, "pip_check": {"ok": check.ok, "tail": scrub(check.tail[-10:], root, env=scratch)}}
        persist()

    if "build" not in stages:
        if not lock_ok:
            stages["build"] = {"ok": False, "skipped": skipped}
        else:
            if not budget.allows(25):
                return pause("the build is next")
            tree = copy_tree(root, scratch / "runs" / "build-tree")
            dist = scratch / "dist"
            if dist.exists():
                shutil.rmtree(dist)
            built = run(
                [uv(), "build", "--wheel", "--out-dir", str(dist), "--python", str(envs.venv_python(scratch)), "--exclude-newer", entry["resolution_date"], "--index-url", envs.INDEX, str(tree)],
                cwd=tree,
                env={**envs.env_for(scratch), **entry.get("build_env", {})},
                timeout=budget.slice(BUILD_TIMEOUT),
            )
            if built.timed_out:
                return pause("the build did not finish")
            wheels = sorted(dist.glob("*.whl")) if dist.is_dir() else []
            wheel = wheels[-1] if built.ok and wheels else None
            stages["build"] = {
                "ok": wheel is not None,
                "wheel": wheel.name if wheel else "",
                "requires_dist": requires_dist(wheel) if wheel else [],
                "seconds": built.seconds,
                "tail": [] if wheel else scrub(built.tail[-20:], root, tree, env=scratch),
            }
        persist()

    if "public" not in stages:
        if not lock_ok:
            stages["public"] = {"ran": False, "ok": False, "skipped": skipped}
        else:
            if not budget.allows(20):
                return pause("the public tests are next")
            note = envs.ensure_venv(entry, scratch, (root / JUDGE_DIR / LOCK).read_text(encoding="utf-8"), budget)
            if note:
                return pause(note)
            tree = copy_tree(root, scratch / "runs" / "public-tree")
            ids = entry["public"]["ids"]
            first = run_suite(tree, entry, scratch, rundir=scratch / "runs" / "judge-public", targets=list(entry["test_dirs"]), timeout=budget.slice(TESTS_TIMEOUT))
            if first.timed_out:
                return pause("the public tests did not finish")
            failed, _ = judged(first, ids)
            reruns: list[str] = []
            if failed and len(failed) <= MAX_LISTED and budget.allows(20):
                again = run_suite(copy_tree(root, scratch / "runs" / "public-tree"), entry, scratch, rundir=scratch / "runs" / "judge-public-rerun", targets=failed, timeout=budget.slice(TESTS_TIMEOUT))
                for test in failed:
                    if again.outcome(test) == "passed":
                        first.outcomes[test] = "passed"
                        reruns.append(test)
            stages["public"] = _tests_record("public", first, ids, reruns=reruns)
        persist()

    if "hidden" not in stages:
        if not lock_ok:
            stages["hidden"] = {"ran": False, "ok": False, "skipped": skipped}
        else:
            if not budget.allows(20):
                return pause("the hidden tests are next")
            files = hidden_files(entry, scratch)
            tree = copy_tree(root, scratch / "runs" / "hidden-tree")
            for rel, content in files.items():
                (tree / rel).parent.mkdir(parents=True, exist_ok=True)
                (tree / rel).write_bytes(content)
            result = run_suite(tree, entry, scratch, rundir=scratch / "runs" / "judge-hidden", targets=list(entry["hidden"]["targets"]), timeout=budget.slice(TESTS_TIMEOUT))
            if result.timed_out:
                return pause("the hidden tests did not finish")
            stages["hidden"] = _tests_record("hidden", result, entry["hidden"]["ids"], extra={"files_digest": catalog.hidden_digest({rel: sha256_bytes(content) for rel, content in files.items()})})
            stages["hidden"].pop("tail", None)
        persist()

    editable_changed = [item for item in changed if matches_any(item["path"], [entry["spec"]["file"], *entry["source_globs"]])]
    if "probe" not in stages:
        if not lock_ok:
            stages["probe"] = {"ran": False, "ok": False, "skipped": skipped, "findings": [], "unexpected": []}
        else:
            if not budget.allows(15):
                return pause("the import probe is next")
            note = envs.ensure_venv(entry, scratch, (root / JUDGE_DIR / LOCK).read_text(encoding="utf-8"), budget)
            if note:
                return pause(note)
            found = probe.run_probe(root, entry, scratch, editable_changed, budget)
            if found.get("timed_out"):
                return pause("the import probe did not finish")
            stages["probe"] = found
        persist()

    if "scan" not in stages:
        # Read twice: with ast (recorded, every rule) and from the tokens (what the verifier reads too).
        recorded = shims.scan(root, editable_changed, entry)
        stages["scan"] = {"ast": recorded, "shims": sorted(set(recorded_problems(recorded, entry)) | set(scan(root, editable_changed, entry)))}
        persist()

    entries_after = tree_entries(root)
    tree_after = tree_hash(entries_after)
    stable = tree_after == tree_now and not state.get("unstable") and changes(manifest["files"], entries_after) == changed
    judgement = {
        "version": 3,
        "complete": True,
        "instance": entry["id"],
        "catalog_sha256": catalog.entry_sha256(entry),
        "setup_token": setup_token(root),
        "base_tree_sha256": entry["base"]["tree_sha256"],
        "target_version": entry["target_version"],
        "tree_sha256": tree_after,
        "tree_stable": stable,
        "changed_files": stages["diff"]["changed"],
        "spec": stages["spec"],
        "lock": stages["lock"],
        "install": stages["install"],
        "build": stages["build"],
        "public": stages["public"],
        "hidden": stages["hidden"],
        "probe": stages["probe"],
        "shims": stages["scan"]["shims"],
        "ast_shims": stages["scan"]["ast"],
        "seconds": round(budget.spent, 2),
        "judged_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    write_json(root / JUDGE_DIR / JUDGEMENT, judgement)
    diff: list[str] = []
    for item in changed:
        pristine = root / JUDGE_DIR / "pristine" / item["path"]
        before = text_lines(pristine.read_bytes()) if pristine.is_file() and item["status"] != "added" else []
        after = text_lines((root / item["path"]).read_bytes()) if item["status"] != "deleted" else []
        diff.extend(unified(item["path"], before, after))
    (root / JUDGE_DIR / DIFF).write_text("\n".join(diff) + "\n", encoding="utf-8")
    progress.pop("judge", None)
    save_progress(root, progress)
    check_workspace_sizes(root)
    return output(recorded=True, complete=True, next_step="")
