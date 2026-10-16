"""The answer key (``pin_upgrade``) and setting an instance up in the workspace (``start_upgrade``):
the upstream repository at the commit before its upgrade, from GitHub's codeload, checked against
the tree hash the catalog validated; its pristine record; and its pre-upgrade environment.

Each process starts an instance afresh (a folder left by an earlier run is replaced); calling start
again in the same run returns the same answer, after rebuilding the environment if needed.
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
from pathlib import Path

from slimconfig import build_output, plain_output

from contract import Breaking, ExcludedTest, PinOutput, PypiFile, StartOutput, UpgradeInput
from plugin import envs, fetch
from plugin.common import (
    JUDGE_DIR,
    Budget,
    ToolError,
    check_workspace_sizes,
    load_json,
    load_progress,
    project_root,
    prune_scratch,
    save_progress,
    scratch_for,
    scratch_home,
    sha256_bytes,
    write_json,
)
from plugin.spec import read as read_spec
from verifier import catalog
from verifier.locks import read_lock, versions_of
from verifier.trees import counts, matches_any, tree_entries, tree_hash
from verifier.versions import canonical_name

READY = "ready.json"
PRISTINE = "pristine.json"
PRISTINE_DIR = "pristine"
LOCK = "requirements.lock"
JUDGEMENT = "judgement.json"
MAX_USES = 20
MAX_BREAKING = 10
MAX_EXCLUDED = 20
# One per plugin process: a project whose ready record carries another run's mark is started afresh.
RUN = secrets.token_hex(8)


def entry_for(instance: str) -> dict:
    try:
        return catalog.entry(instance)
    except ValueError as error:
        raise ToolError(str(error)) from error


def editable_globs(entry: dict) -> list[str]:
    return [entry["spec"]["file"], *entry["source_globs"]]


def is_editable(entry: dict, rel: str) -> bool:
    return matches_any(rel, editable_globs(entry))


def pin_upgrade(given: UpgradeInput, workspace: Path) -> PinOutput:
    """The answer key: the catalog entry's hash, what PyPI serves for the target release right now
    (it must still be the files the instance was validated with), and any judgement already in
    the workspace (a run must judge afresh)."""
    entry = entry_for(given.instance.value)
    release = fetch.pypi_release(entry["dependency"], entry["target_version"])
    expected = sorted((item["filename"], item["sha256"]) for item in entry["target_files"])
    served = sorted((item["filename"], item["sha256"]) for item in release["files"])
    if served != expected:
        raise ToolError(f"PyPI no longer serves {entry['dependency']} {entry['target_version']} as validated: the files or their sha256 differ")
    if release["yanked"]:
        raise ToolError(f"PyPI marks {entry['dependency']} {entry['target_version']} yanked")
    judgement = project_root(workspace, entry["id"]) / JUDGE_DIR / JUDGEMENT
    prior = sha256_bytes(judgement.read_bytes()) if judgement.is_file() else ""
    return PinOutput(
        instance=given.instance,
        catalog_sha256=catalog.entry_sha256(entry),
        dependency=entry["dependency"],
        from_version=entry["from_version"],
        target_version=entry["target_version"],
        pypi_files=[PypiFile(filename=name, sha256=sha) for name, sha in served],
        pypi_yanked=release["yanked"],
        prior_judgement_sha256=prior,
    )


def _moving(entry: dict) -> str:
    """The packages the upgrade may move, each with where it was and where upstream's upgrade put it."""
    base = versions_of(read_lock(catalog.lock_text(entry, "base")))
    gold = versions_of(read_lock(catalog.lock_text(entry, "gold")))
    parts = [f"{name} (stays at {','.join(base.get(canonical_name(name), []))} or moves to {','.join(gold.get(canonical_name(name), []))})" for name in entry.get("allowed_collateral", [])]
    parts += [f"{name} (may come in at {','.join(gold.get(canonical_name(name), []))})" for name in entry.get("allowed_new", [])]
    return "; ".join(parts) or "none"


def rules_for(entry: dict) -> list[str]:
    limits = entry["limits"]
    spec = entry["spec"]
    moving = _moving(entry)
    exclude = f" and exclude {entry['from_version']}" if spec.get("must_exclude_old") else ""
    return [
        f"Goal: {entry['dependency']} {entry['from_version']} -> exactly {entry['target_version']}, with the project building and its tests passing on the new version.",
        (
            f"Only these may change: the requirements in {spec['file']} and source files matching "
            f"{', '.join(entry['source_globs'])} (at most {limits['max_changed_files']} files, {limits['max_new_files']} new, "
            f"{limits['max_added_lines']} added lines). Tests, docs and every other file are read-only."
        ),
        (
            f"Raise {entry['dependency']}'s requirement so it admits {entry['target_version']}{exclude}; sync resolves the spec as of "
            f"{entry['resolution_date'][:10]} with every other package held, and must lock exactly {entry['target_version']}. "
            + (
                f"Keep the other requirements as written, except that packages the upgrade may move can stay or move as upstream's did: {moving}. Every other locked package keeps its version."
                if moving != "none"
                else "Keep the other requirements as written; every other locked package keeps its version."
            )
        ),
        (
            "No shims: nothing that silences or reroutes warnings (filters, catch_warnings, showwarning), no monkeypatching or re-adding the library's old API, no sys.modules or "
            "import tricks, no version or test sniffing, however spelled; migrate the code to the new API (emitting a deprecation warning of your own is fine). "
            "The judge reads the added code and also imports the project to see what it changes."
        ),
        (
            f"Judging runs the repository's own tests ({len(entry['public']['ids'])} judged; {len(entry['public']['excluded'])} not judged, each with why in "
            "excluded_tests) and hidden tests: upstream's own tests after its upgrade"
            + (f" ({len(entry['hidden']['excluded'])} of them not judged: they behave differently on another platform)" if entry["hidden"].get("excluded") else "")
            + ". It also re-locks, installs and builds the wheel."
        ),
        "edit_file (exact old -> new replacements) with then: sync_and_test shows what is left; call judge after your last change, then submit in the same step.",
    ]


def uses_of(root: Path, entry: dict) -> list[str]:
    """``path:line`` where the source imports the dependency."""
    names = "|".join(re.escape(name) for name in entry["import_names"])
    pattern = re.compile(rf"^\s*(?:import|from)\s+(?:{names})\b")
    found = []
    for rel, _ in tree_entries(root):
        if not rel.endswith(".py") or not matches_any(rel, entry["source_globs"]):
            continue
        for number, line in enumerate((root / rel).read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if pattern.match(line):
                found.append(f"{rel}:{number}")
                if len(found) >= MAX_USES:
                    return found
    return found


def fit_note(entry: dict) -> str:
    timing = entry.get("timings", {})
    seconds = timing.get("tool_seconds")
    measured = f" (about {seconds:.0f} s of tool time measured)" if isinstance(seconds, (int, float)) else ""
    if entry.get("fit") == "hosted":
        return f"Fits a hosted run{measured}: start, one edit with sync_and_test, then judge and submit together."
    return f"Local runner only{measured}: set-up and judging take longer than a hosted run allows; run it where tool calls may take minutes."


def excluded_first(entry: dict) -> list[dict]:
    """The public tests not judged, those that behave differently on another platform first."""
    return sorted(entry["public"]["excluded"], key=lambda item: not item["reason"].startswith("platform-dependent"))


def _start_output(root: Path, entry: dict, *, complete: bool, next_step: str, current: str) -> StartOutput:
    spec_file = entry["spec"]["file"]
    requirements, _ = read_spec(entry["spec"]["kind"], (root / spec_file).read_text(encoding="utf-8"), name=spec_file)
    return StartOutput(
        root=f"dep-upgrade/{entry['id']}",
        complete=complete,
        next=next_step,
        repository=entry["repo"],
        dependency=entry["dependency"],
        current_version=current,
        target_version=entry["target_version"],
        spec_file=spec_file,
        current_requirement=envs.dependency_requirement(entry, requirements),
        editable=editable_globs(entry),
        uses=uses_of(root, entry),
        breaking=[Breaking(test=item["test"], error=item["error"]) for item in entry.get("breaking", [])[:MAX_BREAKING]],
        excluded_tests=[ExcludedTest(test=item["id"], reason=item["reason"]) for item in excluded_first(entry)][:MAX_EXCLUDED],
        python=entry["python"],
        fit=entry.get("fit", "local"),
        fit_note=fit_note(entry),
        rules=rules_for(entry),
    )


def ready_root(workspace: Path, instance: str) -> tuple[Path, dict]:
    """The instance's root and catalog entry, once start_upgrade finished in this run."""
    entry = entry_for(instance)
    root = project_root(workspace, entry["id"])
    ready = load_json(root / JUDGE_DIR / READY)
    if not ready or ready.get("run") != RUN:
        raise ToolError(f"start_upgrade {entry['id']} first (set-up is per run)")
    return root, entry


def current_lock(root: Path) -> str:
    path = root / JUDGE_DIR / LOCK
    if not path.is_file():
        raise ToolError("the project has no lock: start_upgrade it again")
    return path.read_text(encoding="utf-8")


def ensure_env(workspace: Path, root: Path, entry: dict, budget: Budget) -> str | None:
    """The scratch venv with the workspace's current lock installed (rebuilt when missing)."""
    return envs.ensure_venv(entry, scratch_for(workspace, entry["id"]), current_lock(root), budget)


def _fresh_checkout(root: Path, entry: dict) -> None:
    """The repository at the commit before the upgrade, checked against the validated tree hash,
    with its pristine record: the manifest and a copy of every editable file."""
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    data = fetch.codeload(entry["repo"], entry["base"]["commit"])
    fetch.unpack(data, root, keep=counts)
    # Files the project's own install would generate (e.g. a setuptools-scm version module).
    for rel, text in entry.get("post_setup", {}).items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    entries = tree_entries(root)
    if tree_hash(entries) != entry["base"]["tree_sha256"]:
        shutil.rmtree(root)
        raise ToolError(f"GitHub served a different tree for {entry['repo']}@{entry['base']['commit'][:12]} than the one validated")
    judge_dir = root / JUDGE_DIR
    write_json(judge_dir / PRISTINE, {"instance": entry["id"], "tree_sha256": tree_hash(entries), "files": dict(entries)})
    for rel, _ in entries:
        if is_editable(entry, rel):
            copy = judge_dir / PRISTINE_DIR / rel
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_bytes((root / rel).read_bytes())
    (judge_dir / LOCK).write_text(catalog.lock_text(entry, "base"), encoding="utf-8")


def start_upgrade(given: UpgradeInput, workspace: Path, *, budget: Budget | None = None) -> StartOutput:
    """Check the repository out at the commit before its upgrade and install its pre-upgrade
    environment outside the workspace. Resumable: a call that runs out of budget returns
    ``complete: false`` and the next call carries on."""
    budget = budget or Budget()
    entry = entry_for(given.instance.value)
    root = project_root(workspace, entry["id"])
    judge_dir = root / JUDGE_DIR
    ready = load_json(judge_dir / READY)
    if ready.get("run") == RUN:
        output = build_output(ready["output"], StartOutput)
        note = ensure_env(workspace, root, entry, budget)
        return output if note is None else _start_output(root, entry, complete=False, next_step=note, current="")
    progress = load_progress(root) if root.exists() else {}
    if progress.get("run") != RUN or not progress.get("checked_out"):
        _fresh_checkout(root, entry)
        progress = {"run": RUN, "checked_out": True}
        save_progress(root, progress)
    note = ensure_env(workspace, root, entry, budget)
    if note:
        save_progress(root, progress)
        return _start_output(root, entry, complete=False, next_step=note, current="")
    scratch = scratch_for(workspace, entry["id"])
    current = envs.installed_versions(scratch, [entry["dependency"]])[entry["dependency"]]
    if current != entry["from_version"]:
        raise ToolError(f"the environment holds {entry['dependency']} {current!r}, expected {entry['from_version']}")
    check_workspace_sizes(root)
    output = _start_output(root, entry, complete=True, next_step="", current=current)
    write_json(judge_dir / READY, {"run": RUN, "setup_token": secrets.token_hex(16), "output": plain_output(output)})
    (judge_dir / JUDGEMENT).unlink(missing_ok=True)
    prune_scratch(scratch_home(workspace))
    return output


def setup_token(root: Path) -> str:
    return str(load_json(root / JUDGE_DIR / READY).get("setup_token", ""))


def ready_record(root: Path) -> dict:
    return json.loads((root / JUDGE_DIR / READY).read_text(encoding="utf-8"))
