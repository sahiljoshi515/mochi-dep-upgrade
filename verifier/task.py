"""The upgrade-dependency outcome check: pure reads of the workspace against the pinned reference
and the judge's record.

Structure gates the verdict (score 0 when any gate fails): the judgement is the project's and
complete, nothing changed after it, tests/ and README.md are pristine, every changed file is allowed and within the
limits, pyproject.toml changed only in its dependencies array and as the rules allow, uv.lock holds
the target from PyPI and every other direct dependency where it was, and no forbidden pattern is in
src/. Then four outcomes score 0.25 each: version (lock consistent and installed), build, public
tests, hidden tests. Valid only at 1.0.
"""

import hashlib
import re
from pathlib import Path

from .checks import project_root, result
from .judge import read_judgement
from .pyproject import blank_dependencies, dependencies, is_project, is_pypi, lock_packages, requires_python
from .trees import is_protected, sha256_of, tree_entries, tree_hash
from .versions import admits, canonical_name, parse_requirement

OUTCOMES = (
    ("version", "Locked and installed the target version"),
    ("build", "Wheel builds"),
    ("public_tests", "Public tests pass"),
    ("hidden_tests", "Hidden tests pass"),
)
ALLOWED_TOP = ("pyproject.toml", "uv.lock")
NO_JUDGEMENT = "no judgement: call judge last"


def _allowed_path(rel, package):
    if rel in ALLOWED_TOP:
        return True
    return rel.startswith(f"src/{package}/") and rel.endswith(".py") and ".." not in rel.split("/")


def _passed(record, expected_ids=None):
    """Whether a recorded pytest run passed outright: exit 0, nothing failed to collect, every
    collected test passed (and exactly ``expected_ids`` collected, when given). Returns
    ``(ok, failed test ids)``."""
    if not isinstance(record, dict):
        return False, []
    collected = record.get("collected") or []
    outcomes = record.get("outcomes") or {}
    if not isinstance(collected, list) or not isinstance(outcomes, dict):
        return False, []
    failed = sorted(test for test in collected if outcomes.get(test) != "passed")
    ok = record.get("exit_status") == 0 and bool(collected) and not record.get("collection_errors") and not failed
    if expected_ids is not None and set(collected) != set(expected_ids):
        ok = False
    return bool(ok and record.get("ok") is True), failed


def _scan(src, patterns):
    found = []
    compiled = []
    for pattern in patterns:
        try:
            compiled.append((pattern, re.compile(pattern)))
        except re.error:
            found.append(f"unreadable forbidden pattern: {pattern}")
    for path in sorted(Path(src).rglob("*.py")):
        if {"__pycache__", ".venv", ".judge"} & set(path.relative_to(src).parts):
            continue
        rel = path.relative_to(Path(src).parent).as_posix()
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for pattern, regex in compiled:
                if regex.search(line):
                    found.append(f"{rel}:{number}: {pattern}")
    return found[:50]


def verify_task(arguments, reference, workspace):
    pin = reference
    project = arguments.project
    report = {"project": project.value, "dependency": pin.dependency, "from_version": pin.from_version, "target_version": pin.target_version}
    if pin.project != project:
        return result(False, "the pinned reference is for another project", score=0.0, **report)
    root = project_root(workspace, project)
    judgement = read_judgement(workspace, project)
    if judgement is None:
        return result(False, NO_JUDGEMENT, score=0.0, checks=[], violations=[NO_JUDGEMENT], **report)
    if judgement.get("project") != project.value:
        return result(False, "the judgement is for another project", score=0.0, checks=[], violations=["judgement project"], **report)
    if judgement.get("complete") is not True:
        message = "the judge did not finish: call judge again until it reports complete"
        return result(False, message, score=0.0, checks=[], violations=[message], **report)

    problems = []
    if judgement.get("dependency") != pin.dependency or judgement.get("target_version") != pin.target_version:
        problems.append("the judgement is for another upgrade")
    if judgement.get("pristine_tree_sha256") != pin.pristine_tree_sha256:
        problems.append("the judge ran against another pristine project")
    if judgement.get("hidden_tests_sha256") != pin.hidden_tests_sha256:
        problems.append("the judge ran other hidden tests")
    if judgement.get("tree_stable") is not True:
        problems.append("files changed while the judge was running")

    entries = tree_entries(root)
    if tree_hash(entries) != judgement.get("tree_sha256"):
        problems.append("files changed after the judge ran")
    if tree_hash(entry for entry in entries if is_protected(entry[0])) != pin.protected_tree_sha256:
        problems.append("tests/ or README.md differ from the pristine project")
    pyproject_path = root / "pyproject.toml"
    lock_path = root / "uv.lock"
    if not pyproject_path.is_file() or sha256_of(pyproject_path) != judgement.get("pyproject_sha256"):
        problems.append("pyproject.toml differs from the judged one")
    if not lock_path.is_file() or sha256_of(lock_path) != judgement.get("uv_lock_sha256"):
        problems.append("uv.lock differs from the judged one")

    changed = judgement.get("changed_files")
    changed_paths = []
    new_files = 0
    added_lines = 0
    if not isinstance(changed, list):
        problems.append("the judgement lists no changed files")
        changed = []
    for entry in changed:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            problems.append("a changed-file entry is malformed")
            continue
        rel = entry["path"]
        status = entry.get("status")
        changed_paths.append(f"{rel} ({status})")
        if status == "deleted":
            problems.append(f"file removed: {rel}")
            continue
        if not _allowed_path(rel, pin.package):
            problems.append(f"file may not change: {rel}")
        path = root / rel
        if not path.is_file() or sha256_of(path) != entry.get("sha256"):
            problems.append(f"file changed after the judge ran: {rel}")
        if status == "added":
            new_files += 1
        lines = entry.get("added_lines")
        added_lines += lines if isinstance(lines, int) and lines > 0 else 0
    if new_files > pin.max_new_files:
        problems.append(f"{new_files} new files, over the limit of {pin.max_new_files}")
    if added_lines > pin.max_added_lines:
        problems.append(f"{added_lines} added lines, over the limit of {pin.max_added_lines}")

    dependency = canonical_name(pin.dependency)
    collateral = {canonical_name(name) for name in pin.allowed_collateral}
    allowed_new = {canonical_name(name) for name in pin.allowed_new_dependencies}
    if pyproject_path.is_file():
        text = pyproject_path.read_text(encoding="utf-8")
        if hashlib.sha256(blank_dependencies(text).encode("utf-8")).hexdigest() != pin.pyproject_rest_sha256:
            problems.append("pyproject.toml changed outside its [project] dependencies array")
        if requires_python(text) != pin.requires_python:
            problems.append("requires-python changed")
        try:
            written = dependencies(text)
            requirements = [parse_requirement(item) for item in written]
        except ValueError as error:
            problems.append(f"pyproject.toml dependencies are unreadable: {error}")
            written, requirements = [], []
        names = [requirement.name for requirement in requirements]
        if len(set(names)) != len(names):
            problems.append("a requirement is listed twice")
        if any(requirement.url for requirement in requirements):
            problems.append("a requirement points at a URL instead of PyPI")
        targets = [requirement for requirement in requirements if requirement.name == dependency]
        if len(targets) != 1:
            problems.append(f"{pin.dependency} must be required exactly once")
        else:
            target = targets[0]
            if target.marker:
                problems.append(f"{pin.dependency} must be required unconditionally")
            if not target.specifier or not admits(target.specifier, pin.target_version):
                problems.append(f"the requirement for {pin.dependency} does not admit {pin.target_version}")
            elif admits(target.specifier, pin.from_version):
                problems.append(f"the requirement for {pin.dependency} still admits {pin.from_version}")
        pristine = {}
        for item in pin.pristine_dependencies:
            try:
                pristine[parse_requirement(item).name] = item
            except ValueError:
                problems.append(f"the pinned requirement is unreadable: {item}")
        for requirement, raw in zip(requirements, written):
            if requirement.name == dependency:
                continue
            if requirement.name in pristine:
                if raw != pristine[requirement.name] and requirement.name not in collateral:
                    problems.append(f"requirement changed: {requirement.raw_name}")
            elif requirement.name not in allowed_new:
                problems.append(f"requirement added that is not allowed: {requirement.raw_name}")
        for name in pristine:
            if name != dependency and name not in names:
                problems.append(f"requirement removed: {name}")

    if lock_path.is_file():
        packages = lock_packages(lock_path.read_text(encoding="utf-8"))
        by_name = {canonical_name(package["name"]): package for package in packages}
        locked = by_name.get(dependency)
        if locked is None:
            problems.append(f"uv.lock does not hold {pin.dependency}")
        else:
            if locked["version"] != pin.target_version:
                problems.append(f"uv.lock holds {pin.dependency} {locked['version']}, not {pin.target_version}")
            if not is_pypi(locked["source"]):
                problems.append(f"uv.lock takes {pin.dependency} from outside PyPI")
        for name, version in pin.other_dependencies.items():
            if name in collateral:
                continue
            package = by_name.get(name)
            if package is None or package["version"] != version:
                problems.append(f"locked version changed: {name}")
        for package in packages:
            if not (is_pypi(package["source"]) or is_project(package["source"])):
                problems.append(f"a package comes from outside PyPI: {package['name']}")

    violations = list(judgement.get("forbidden") or [])
    if (root / "src").is_dir():
        for found in _scan(root / "src", pin.forbidden_patterns):
            if found not in violations:
                violations.append(found)
    problems += [f"forbidden pattern: {found}" for found in violations]

    installed = judgement.get("installed") if isinstance(judgement.get("installed"), dict) else {}
    installed_version = installed.get(pin.dependency, "") if isinstance(installed, dict) else ""
    lock_ok = isinstance(judgement.get("lock_check"), dict) and judgement["lock_check"].get("ok") is True
    version_ok = lock_ok and installed_version == pin.target_version
    build_ok = isinstance(judgement.get("build"), dict) and judgement["build"].get("ok") is True
    public_ok, public_failed = _passed(judgement.get("public"))
    hidden_ok, hidden_failed = _passed(judgement.get("hidden"), pin.hidden_test_ids)
    outcomes = {"version": version_ok, "build": build_ok, "public_tests": public_ok, "hidden_tests": hidden_ok}
    checks = [
        {"id": "structure", "label": "Only allowed changes, nothing touched after judging", "ok": not problems, "message": "; ".join(problems[:5]) or "ok"},
    ] + [
        {"id": key, "label": label, "ok": outcomes[key], "message": _outcome_message(key, outcomes[key], installed_version, lock_ok, public_failed, hidden_failed, pin)}
        for key, label in OUTCOMES
    ]
    details = {
        **report,
        "installed_version": installed_version,
        "checks": checks,
        "changed_files": changed_paths,
        "new_files": new_files,
        "added_lines": added_lines,
        "violations": problems,
        "failed_tests": {"public": public_failed, "hidden": hidden_failed},
    }
    if problems:
        return result(False, f"{len(problems)} problem(s): {problems[0]}", score=0.0, **details)
    score = sum(0.25 for key in outcomes if outcomes[key])
    if score < 1.0:
        failed = [label for key, label in OUTCOMES if not outcomes[key]]
        return result(False, "not done: " + "; ".join(failed), score=score, **details)
    return result(True, f"{pin.dependency} {pin.from_version} -> {pin.target_version}: locked, built, public and hidden tests pass", score=1.0, **details)


def _outcome_message(key, ok, installed_version, lock_ok, public_failed, hidden_failed, pin):
    if ok:
        return "ok"
    if key == "version":
        if not lock_ok:
            return "uv.lock does not match pyproject.toml"
        return f"installed {installed_version or 'nothing'}, expected {pin.target_version}"
    if key == "build":
        return "uv build --wheel failed"
    if key == "public_tests":
        return f"{len(public_failed)} public test(s) did not pass" if public_failed else "the public tests did not run clean"
    return f"{len(hidden_failed)} hidden test(s) did not pass" if hidden_failed else "the hidden tests did not run clean"
