"""The upgrade-dependency verdict: 19 ordered constraints, each checked by pure reads of the workspace
against the catalog entry, the pinned answer key and the judge's record.

What the verifier recomputes itself, trusting no tool: the pristine record (against the catalog's
tree hash), every changed file and added line (against the pristine copies), the spec's requirements
(with its own reader), the lock's pins and hashes (against PyPI's files, read when the task started,
and the validated post-upgrade lock), and the shim scan. What only the judge can do (installing,
building, running the tests) it takes from the judgement, once that is shown to be this run's, for
this instance, with nothing changed after it.
"""

import hashlib
import json

from . import catalog
from .checks import Constraints, project_root, short
from .locks import read_lock, versions_of
from .shims import added_lines_by_file, pristine_manifest, recorded_problems, scan
from .specs import read_spec
from .trees import changes, matches_any, sha256_of, text_lines, tree_entries, tree_hash, unified
from .versions import admits, canonical_name, parse_requirement, requirement_key

JUDGEMENT = "judgement.json"
READY = "ready.json"
LOCK = "requirements.lock"
MAX_DIFF_LINES = 200


def read_json(path):
    """``(data, raw bytes)``, or ``(None, b"")`` when the file is missing or not a JSON object."""
    if not path.is_file():
        return None, b""
    raw = path.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None, raw
    return (data if isinstance(data, dict) else None), raw


def dependency_requirements(entry, requirements):
    wanted = canonical_name(entry["dependency"])
    found = []
    for text in requirements:
        try:
            if parse_requirement(text).name == wanted:
                found.append(text)
        except ValueError:
            continue
    return found


def spec_scope_problems(entry, requirements, base_requirements):
    """Every way the spec's requirements go beyond raising the dependency (and what moves with it)."""
    problems = []
    parsed = []
    for text in requirements:
        try:
            parsed.append((text, parse_requirement(text)))
        except ValueError as error:
            problems.append(f"unreadable requirement {text!r}: {error}")
    names = [requirement.name for _, requirement in parsed]
    for name in sorted({name for name in names if names.count(name) > 1}):
        problems.append(f"{name} is required more than once")
    dependency = canonical_name(entry["dependency"])
    base = {}
    for text in base_requirements:
        requirement = parse_requirement(text)
        base[requirement.name] = (text, requirement)
    collateral = {canonical_name(name) for name in entry.get("allowed_collateral", [])}
    allowed_new = {canonical_name(name) for name in entry.get("allowed_new", [])}
    for text, requirement in parsed:
        if requirement.url:
            problems.append(f"{requirement.raw_name} points at a URL instead of PyPI")
            continue
        if requirement.name == dependency:
            had_marker = dependency in base and base[dependency][1].marker
            if requirement.marker and not had_marker:
                problems.append(f"{requirement.raw_name} must be required unconditionally")
            continue
        if requirement.name in base:
            if requirement_key(text) != requirement_key(base[requirement.name][0]) and requirement.name not in collateral:
                problems.append(f"requirement changed that the upgrade does not need: {text}")
        elif requirement.name not in allowed_new:
            problems.append(f"requirement added that is not allowed: {requirement.raw_name}")
    for name, (text, _) in base.items():
        if name != dependency and name not in names:
            problems.append(f"requirement removed: {text}")
    if dependency not in names:
        problems.append(f"{entry['dependency']} is no longer required")
    return problems


def lock_scope_problems(current, base, gold, entry):
    """Every package other than the dependency that the judged lock holds where neither the pre-upgrade
    lock nor upstream's validated upgrade has it. Each package may keep its pre-upgrade version (or stay
    out); one the upgrade moves (allowed collateral), brings in (allowed new) or drops may instead be
    where upstream's lock has it. Messages say what the judged lock holds against what was allowed."""
    dependency = canonical_name(entry["dependency"])
    collateral = {canonical_name(name) for name in entry.get("allowed_collateral", [])}
    now, before, after = versions_of(current), versions_of(base), versions_of(gold)
    problems = []
    for name in sorted((set(now) | set(before) | set(after)) - {dependency}):
        have, was, upstream = now.get(name), before.get(name), after.get(name)
        if have in (was, upstream):
            continue
        shown = ",".join(have or [])
        if have is None:
            problems.append(f"{name} is missing from the lock; the upgrade keeps it at {','.join(was or upstream)}")
        elif was is None and upstream is None:
            problems.append(f"{name} {shown} came into the lock; the upgrade brings in no {name}")
        elif was is None:
            problems.append(f"{name} came into the lock at {shown}; the upgrade may bring it in at {','.join(upstream)} only")
        elif name in collateral and upstream is not None:
            problems.append(f"{name} is locked at {shown}; it may stay at {','.join(was)} or move to {','.join(upstream)}, as upstream's upgrade did")
        else:
            problems.append(f"{name} moved from {','.join(was)} to {shown}; the upgrade keeps it at {','.join(was)}")
    return problems


def diff_lines(root, changed):
    out = []
    for item in changed:
        rel = item["path"]
        pristine = root / ".judge" / "pristine" / rel
        before = text_lines(pristine.read_bytes()) if pristine.is_file() and item["status"] != "added" else []
        after = text_lines((root / rel).read_bytes()) if item["status"] != "deleted" else []
        out.extend(unified(rel, before, after))
        if len(out) >= MAX_DIFF_LINES:
            return out[:MAX_DIFF_LINES] + ["... (diff cut)"]
    return out


def verify_task(arguments, output, reference, workspace):
    instance = arguments.instance.value
    entry = catalog.entry(instance)
    entry_sha = catalog.entry_sha256(entry)
    root = project_root(workspace, instance)
    dependency, target, old = entry["dependency"], entry["target_version"], entry["from_version"]
    dep = canonical_name(dependency)
    spec = entry["spec"]
    editable = [spec["file"], *entry["source_globs"]]
    expected_files = sorted((item["filename"], item["sha256"]) for item in entry["target_files"])
    c = Constraints()

    # 1. The answer key: PyPI still serves the target release exactly as validated.
    if reference is None:
        c.add("instance_pinned", f"PyPI still serves {dependency} {target} as validated", False, message="No answer key was pinned for this run")
        pypi_hashes = set()
    else:
        served = sorted((item.filename, item.sha256) for item in reference.pypi_files)
        problems = []
        if reference.instance != arguments.instance or reference.catalog_sha256 != entry_sha:
            problems.append("The answer key was pinned for another instance or catalog")
        if served != expected_files:
            problems.append(f"PyPI no longer serves {dependency} {target} as validated")
        if reference.pypi_yanked:
            problems.append(f"PyPI marks {dependency} {target} yanked")
        c.add(
            "instance_pinned",
            f"PyPI still serves {dependency} {target} as validated",
            not problems,
            expected=[name for name, _ in expected_files],
            actual=[name for name, _ in served],
            message="; ".join(problems),
        )
        pypi_hashes = {sha for _, sha in served}

    # 2. The submission's facts.
    facts = {"instance": output.instance.value, "dependency": canonical_name(output.dependency), "from_version": output.from_version.strip(), "to_version": output.to_version.strip()}
    want = {"instance": instance, "dependency": dep, "from_version": old, "to_version": target}
    wrong = [key for key in want if facts[key] != want[key]]
    c.add(
        "submitted_facts",
        "The submission names this instance, its dependency and both versions",
        not wrong,
        expected=want,
        actual=facts,
        message=(f"The submission says {wrong[0]} {facts[wrong[0]]!r}; it is {want[wrong[0]]!r}" if wrong else ""),
    )

    # 3. Migration notes.
    notes = [note.strip() for note in output.migration]
    out_of_range = [note for note in notes if not 10 <= len(note) <= 200]
    c.add(
        "migration_notes",
        "The submission explains the migration in 1 to 8 notes of 10 to 200 characters",
        1 <= len(notes) <= 8 and not out_of_range,
        expected="1-8 notes, 10-200 characters each",
        actual=f"{len(notes)} notes, {len(out_of_range)} out of range",
        message=f"The submission needs 1 to 8 migration notes of 10 to 200 characters (got {len(notes)}, {len(out_of_range)} out of range)",
    )

    # 4. A complete judgement for this instance.
    judgement, raw = read_json(root / ".judge" / JUDGEMENT)
    if judgement is None:
        judged = c.add("judged", "The judge recorded a complete judgement", False, message="No judgement: call judge after your last change")
    elif judgement.get("complete") is not True:
        judged = c.add("judged", "The judge recorded a complete judgement", False, message="Judging did not finish: call judge again until it reports complete")
    else:
        judged = c.add(
            "judged",
            "The judge recorded a complete judgement",
            judgement.get("version") == 3 and judgement.get("instance") == instance,
            message="The judgement is for another instance or format",
        )

    # The pristine record, against the catalog: what every workspace check is measured from.
    manifest = pristine_manifest(root) if root.is_dir() else None
    pristine_ok = manifest is not None and manifest.get("instance") == instance and tree_hash(manifest["files"].items()) == entry["base"]["tree_sha256"]
    if pristine_ok:
        for rel in [path for path in manifest["files"] if matches_any(path, editable)]:
            copy = root / ".judge" / "pristine" / rel
            if not copy.is_file() or sha256_of(copy) != manifest["files"][rel]:
                pristine_ok = False
                break
    no_project = "the project was never set up here (start_upgrade)" if manifest is None else "the pristine record was altered"
    entries = tree_entries(root) if pristine_ok else []
    changed = changes(manifest["files"], entries) if pristine_ok else []
    derived = [item["path"] for item in changed]
    # Added lines and shims are counted in the editable files only; a change anywhere else already
    # fails allowed_files_only.
    editable_changed = [item for item in changed if matches_any(item["path"], editable)]
    added = added_lines_by_file(root, editable_changed) if pristine_ok else {}

    # 5. This run's judgement.
    ready, _ = read_json(root / ".judge" / READY)
    if not judged:
        c.skip("judged_this_run", "The judgement was made in this run, after this set-up", "no complete judgement")
    else:
        fresh = reference is not None and hashlib.sha256(raw).hexdigest() != reference.prior_judgement_sha256
        token = (ready or {}).get("setup_token", "")
        same_setup = bool(token) and judgement.get("setup_token") == token
        c.add(
            "judged_this_run",
            "The judgement was made in this run, after this set-up",
            fresh and same_setup,
            message=("The judgement is from an earlier run: call judge in this run" if not fresh else "The judgement does not belong to this set-up: start_upgrade, then judge"),
        )

    # 6. The judgement judged this instance as catalogued.
    if not judged:
        c.skip("judgement_consistent", "The judgement used this instance's catalog entry, pristine tree and hidden tests", "no complete judgement")
    else:
        hidden = judgement.get("hidden") or {}
        mismatched = []
        if judgement.get("catalog_sha256") != entry_sha:
            mismatched.append("catalog entry")
        if judgement.get("base_tree_sha256") != entry["base"]["tree_sha256"]:
            mismatched.append("pristine tree")
        if hidden.get("ran") and hidden.get("files_digest") != catalog.hidden_digest(entry["hidden"]["files"]):
            mismatched.append("hidden tests")
        c.add(
            "judgement_consistent",
            "The judgement used this instance's catalog entry, pristine tree and hidden tests",
            not mismatched,
            message="The judgement used another " + ", ".join(mismatched) if mismatched else "",
        )

    # 7. Nothing changed after (or while) judging.
    if not judged:
        c.skip("files_as_judged", "The files are exactly as the judge saw them", "no complete judgement")
    elif not pristine_ok:
        c.skip("files_as_judged", "The files are exactly as the judge saw them", no_project)
    else:
        recorded = {item.get("path"): item.get("sha256") for item in judgement.get("changed_files", []) if isinstance(item, dict)}
        now = {item["path"]: item["sha256"] for item in changed}
        drift = sorted(path for path in set(recorded) | set(now) if recorded.get(path) != now.get(path))
        same_tree = tree_hash(entries) == judgement.get("tree_sha256")
        stable = judgement.get("tree_stable") is True
        c.add(
            "files_as_judged",
            "The files are exactly as the judge saw them",
            same_tree and stable and not drift,
            expected=judgement.get("tree_sha256"),
            actual=tree_hash(entries),
            message=(f"{drift[0]} changed after the judge ran" if drift else ("Files changed after the judge ran" if not same_tree else "Files changed while the judge was running")),
        )

    # 8. The submission matches the work.
    requirement_now = ""
    spec_requirements = None
    spec_problem = ""
    if pristine_ok:
        try:
            spec_requirements, blanked_now = read_spec(spec["kind"], (root / spec["file"]).read_bytes().decode("utf-8"))
            for text in spec_requirements:
                parse_requirement(text)
            found = dependency_requirements(entry, spec_requirements)
            requirement_now = found[0] if len(found) == 1 else ""
        except (ValueError, UnicodeDecodeError, OSError) as error:
            spec_problem = f"{spec['file']} cannot be read: {error}"
    if not pristine_ok:
        c.skip("submission_matches", "The submission lists exactly the changed files and the spec's requirement", no_project)
    else:
        submitted = sorted({path.strip() for path in output.changed_files})
        extra = [path for path in submitted if path not in derived]
        missing = [path for path in derived if path not in submitted]
        submitted_problem = ""
        try:
            same_requirement = bool(requirement_now) and requirement_key(output.requirement) == requirement_key(requirement_now)
        except ValueError as error:
            same_requirement, submitted_problem = False, f"The submission's requirement {output.requirement!r} is not valid: {error}"
        if spec_problem:
            message = spec_problem
        elif extra:
            message = "The submission lists files that did not change: " + ", ".join(short(extra, 5))
        elif missing:
            message = "The submission leaves out changed files: " + ", ".join(short(missing, 5))
        elif submitted_problem:
            message = submitted_problem
        else:
            message = f"The submission states the requirement {output.requirement!r}; the spec says {requirement_now!r}"
        c.add(
            "submission_matches",
            "The submission lists exactly the changed files and the spec's requirement",
            not spec_problem and not extra and not missing and same_requirement,
            expected={"changed_files": derived, "requirement": requirement_now},
            actual={"changed_files": submitted, "requirement": output.requirement},
            message=message,
        )

    # 9. Only the spec and the package's source changed.
    if not pristine_ok:
        c.skip("allowed_files_only", "Only the spec's requirements and the package's source changed", no_project)
    else:
        outside = [item["path"] for item in changed if not matches_any(item["path"], editable)]
        deleted = [item["path"] for item in changed if item["status"] == "deleted"]
        c.add(
            "allowed_files_only",
            "Only the spec's requirements and the package's source changed",
            not outside and not deleted,
            expected=editable,
            actual=short(outside + deleted, 10),
            message=(f"{outside[0]} may not change" if outside else (f"{deleted[0]} was deleted" if deleted else "")),
        )

    # 10. Within the instance's limits.
    limits = entry["limits"]
    if not pristine_ok:
        c.skip("within_limits", "The change stays within the instance's limits", no_project)
    else:
        files_changed = len(changed)
        files_new = sum(1 for item in changed if item["status"] == "added")
        lines_added = sum(len(lines) for lines in added.values())
        over = []
        if files_changed > limits["max_changed_files"]:
            over.append(f"{files_changed} files changed (at most {limits['max_changed_files']})")
        if files_new > limits["max_new_files"]:
            over.append(f"{files_new} new files (at most {limits['max_new_files']})")
        if lines_added > limits["max_added_lines"]:
            over.append(f"{lines_added} added lines (at most {limits['max_added_lines']})")
        c.add(
            "within_limits",
            "The change stays within the instance's limits",
            not over,
            expected=limits,
            actual={"max_changed_files": files_changed, "max_new_files": files_new, "max_added_lines": lines_added},
            message="; ".join(over),
        )

    # 11. The spec changed only as the upgrade needs.
    if not pristine_ok:
        c.skip("spec_scope", "The spec changed only the dependency's requirement (and what moves with it)", no_project)
    elif spec_problem:
        c.add("spec_scope", "The spec changed only the dependency's requirement (and what moves with it)", False, message=spec_problem)
    else:
        pristine_text = (root / ".judge" / "pristine" / spec["file"]).read_bytes().decode("utf-8")
        base_requirements, blanked_base = read_spec(spec["kind"], pristine_text)
        problems = []
        if blanked_now != blanked_base:
            problems.append(f"only the requirements in {spec['file']} may change; the rest of the file changed too")
        problems += spec_scope_problems(entry, spec_requirements, base_requirements)
        c.add(
            "spec_scope",
            "The spec changed only the dependency's requirement (and what moves with it)",
            not problems,
            expected=base_requirements,
            actual=spec_requirements,
            message="; ".join(problems[:3]),
        )

    # 12. The requirement admits the target (and excludes the old version when upstream's does).
    exclude = bool(spec.get("must_exclude_old"))
    constraint = f"{dependency}'s requirement admits {target}" + (f" and excludes {old}" if exclude else "")
    if not pristine_ok:
        c.skip("spec_admits_target", constraint, no_project)
    elif spec_problem:
        c.add("spec_admits_target", constraint, False, message=spec_problem)
    elif not requirement_now:
        c.add("spec_admits_target", constraint, False, message=f"The spec does not state {dependency}'s requirement exactly once")
    else:
        try:
            specifier = parse_requirement(requirement_now).specifier
            admits_target = admits(specifier, target)
            admits_old = admits(specifier, old)
        except ValueError:
            admits_target, admits_old = False, True
        ok = admits_target and not (exclude and admits_old)
        c.add(
            "spec_admits_target",
            constraint,
            ok,
            expected=f"admits {target}" + (f", excludes {old}" if exclude else ""),
            actual=requirement_now,
            message=(f"The requirement {requirement_now} does not admit {target}" if not admits_target else f"The requirement {requirement_now} still admits {old}"),
        )

    # 13. The judged lock pins exactly the target, from PyPI's files.
    lock_path = root / ".judge" / LOCK
    lock_packages = None
    if not judged:
        c.skip("lock_target", f"The lock pins {dependency} {target} with PyPI's hashes", "no complete judgement")
    else:
        lock = judgement.get("lock") or {}
        problem = ""
        if not lock.get("ok"):
            problem = "The spec did not resolve when judged: " + " ".join((lock.get("tail") or [])[-2:])[:300]
        elif not lock_path.is_file() or sha256_of(lock_path) != lock.get("sha256"):
            problem = "The lock changed after judging"
        else:
            try:
                lock_packages = read_lock(lock_path.read_text(encoding="utf-8"))
            except (ValueError, UnicodeDecodeError) as error:
                problem = f"The lock cannot be read: {error}"
        if not problem:
            pins = lock_packages.get(dep, [])
            versions = sorted({pin["version"] for pin in pins})
            hashes = {sha for pin in pins for sha in pin["hashes"]}
            if versions != [target]:
                problem = f"The lock holds {dependency} {', '.join(versions) or 'nothing'}, not {target}"
            elif not hashes or not hashes <= pypi_hashes:
                problem = f"The lock's hashes for {dependency} are not the ones PyPI serves for {target}"
        c.add("lock_target", f"The lock pins {dependency} {target} with PyPI's hashes", not problem, expected=target, actual=(sorted({pin["version"] for pin in (lock_packages or {}).get(dep, [])}) if lock_packages else None), message=problem)

    # 14. Nothing else in the lock moved beyond the validated upgrade.
    scope_label = "Every other locked package keeps its version, or takes upstream's where the upgrade moves it"
    if lock_packages is None:
        c.skip("lock_scope", scope_label, "no readable judged lock")
    else:
        moved = lock_scope_problems(lock_packages, read_lock(catalog.lock_text(entry, "base")), read_lock(catalog.lock_text(entry, "gold")), entry)
        c.add("lock_scope", scope_label, not moved, actual=short(moved, 10), message=(moved[0] if moved else ""))

    # 15. Installed for judging.
    if not judged:
        c.skip("installed_target", f"{dependency} {target} was installed for judging and the environment is consistent", "no complete judgement")
    else:
        install = judgement.get("install") or {}
        installed = (install.get("installed") or {}).get(dep, "")
        check = (install.get("pip_check") or {}).get("ok") is True
        c.add(
            "installed_target",
            f"{dependency} {target} was installed for judging and the environment is consistent",
            bool(install.get("ok")) and installed == target and check,
            expected=target,
            actual=installed or None,
            message=(f"Installed {installed or 'nothing'}, not {target}" if installed != target else "uv pip check found conflicts in the judged environment"),
        )

    # 16. The wheel builds, and what it declares for the dependency admits the target.
    label = f"The project's wheel builds and its requirement on {dependency} admits {target}"
    if not judged:
        c.skip("builds", label, "no complete judgement")
    else:
        build = judgement.get("build") or {}
        declared = []
        for text in build.get("requires_dist") or []:
            try:
                requirement = parse_requirement(text)
            except ValueError:
                continue
            if requirement.name == dep:
                declared.append(requirement)
        admitted = bool(declared) and all(admits(requirement.specifier, target) for requirement in declared)
        if not build.get("ok"):
            message = "The wheel did not build: " + " ".join((build.get("tail") or [])[-2:])[:300]
        elif not declared:
            message = f"The built wheel does not declare {dependency}"
        else:
            message = f"The built wheel requires {', '.join(requirement.text for requirement in declared)}, which does not admit {target}"
        c.add("builds", label, bool(build.get("ok")) and admitted, expected=f"admits {target}", actual=[requirement.text for requirement in declared], message=message)

    # 17-18. The tests.
    for cid, kind, label in (("public_tests_pass", "public", "The repository's judged tests pass"), ("hidden_tests_pass", "hidden", "Upstream's post-upgrade tests pass")):
        if not judged:
            c.skip(cid, label, "no complete judgement")
            continue
        record = judgement.get(kind) or {}
        ids = entry[kind]["ids"]
        right_set = record.get("ids_sha256") == catalog.ids_sha256(ids)
        failed = record.get("failed") or []
        missing = record.get("missing") or []
        ok = bool(record.get("ok")) and right_set and not failed and not missing and record.get("failed_count", 0) == 0 and record.get("missing_count", 0) == 0
        if not record.get("ran"):
            message = f"The {kind} tests did not run: {record.get('skipped', 'no environment')}"
        elif not right_set:
            message = f"The judge ran another set of {kind} tests"
        elif failed or record.get("failed_count"):
            message = f"{record.get('failed_count', len(failed))} {kind} test(s) did not pass" + (f", e.g. {failed[0]}" if kind == "public" and failed else "")
        elif missing or record.get("missing_count"):
            message = f"{record.get('missing_count', len(missing))} {kind} test(s) were not collected"
        else:
            message = f"The {kind} test run did not finish cleanly"
        c.add(cid, label, ok, expected=len(ids), actual=record.get("passed"), message=message)

    # 19. No shims: none in the code the change adds (read here from its tokens, and by the judge with
    # ast), none in what importing the project does (the judge's import probe).
    shim_label = "No shim in the added code or in what importing the project does (warning filters, patching, import tricks, sniffing)"
    if not pristine_ok:
        c.skip("no_shims", shim_label, no_project)
    else:
        found = scan(root, editable_changed, entry)
        if judged:
            records = judgement.get("ast_shims")
            found += [item for item in recorded_problems(records if isinstance(records, list) else [], entry) if item not in found]
        problems = [f"Shim at {item}" for item in sorted(found, key=lambda text: (text.split(":")[0], int(text.split(":")[1]) if text.split(":")[1].isdigit() else 0))]
        if judged:
            if not isinstance(judgement.get("ast_shims"), list):
                problems.append("The judge did not read the added code")
            record = judgement.get("probe")
            if not isinstance(record, dict):
                problems.append("The judge did not run the import probe")
            elif record.get("ran"):
                expected = set(entry.get("probe_expected", []))
                problems += [f"Importing the project {finding}" for finding in record.get("findings") or [] if finding not in expected]
            elif (judgement.get("lock") or {}).get("ok"):
                problems.append("The import probe did not run")
        c.add("no_shims", shim_label, not problems, actual=short(problems, 10), message=(problems[0] if problems else ""))

    hidden = (judgement or {}).get("hidden") or {}
    public = (judgement or {}).get("public") or {}
    details = {
        "instance": instance,
        "repository": entry["repo"],
        "dependency": dependency,
        "from_version": old,
        "target_version": target,
        "fit": entry.get("fit", "local"),
        "changed_files": derived,
        "added_lines": sum(len(lines) for lines in added.values()),
        "diff": diff_lines(root, changed) if pristine_ok else [],
        "failed_tests": {"public": short(public.get("failed") or [], 10), "hidden": hidden.get("failed_count", 0)},
        "provenance": {
            "base_commit": entry["base"]["commit"],
            "upstream_commit": entry["upstream"]["url"],
            "pypi_files": [name for name, _ in expected_files],
            "resolution_date": entry["resolution_date"],
        },
    }
    success = f"{dependency} {old} -> {target} locked from PyPI's files, installed and built; {len(entry['public']['ids'])} public and {len(entry['hidden']['ids'])} hidden tests pass"
    return c.verdict(success, **details)
