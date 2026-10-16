"""Scripted cases for the harness (``~/mochi-dev/harness/scripted_task.py``) and the replay tests:
a gold case per catalog instance (upstream's own change, as exact edit_file replacements) and the
adversarial rows on chosen instances.

    uv run python -m plugin.tools_dev.cases [--adversarial <instance> ...] [--out tests/cases]

Upstream's change is read from the onboarding work folder (``<work>/<instance>/{base,c}``), so run
the oracle first.
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

from plugin.tools_dev.onboard import WORK
from verifier import catalog
from verifier.versions import parse_requirement

OUT = Path(__file__).resolve().parents[3] / "tests" / "cases"


def make_edits(rel: str, before: str, after: str) -> list[dict]:
    """Exact replacements that turn ``before`` into ``after``: one per hunk, bottom hunk first (lines
    above it are still as they were), each widened with context until it occurs once. Hunks whose
    context would take in lines a later replacement rewrites are merged, so that every replacement's
    new text is still in the file at the end, as edit_file checks."""
    a = before.splitlines(keepends=True)
    b = after.splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    hunks = [[i1, i2, j1, j2] for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag != "equal"]
    while True:
        edits, clash = place_hunks(rel, a, b, hunks)
        if clash is None:
            return edits
        upper, lower = hunks[clash - 1], hunks[clash]
        hunks[clash - 1:clash + 1] = [[upper[0], lower[1], upper[2], lower[3]]]


def place_hunks(rel: str, a: list[str], b: list[str], hunks: list[list[int]]) -> tuple[list[dict], int | None]:
    """The replacements for ``hunks``, applied bottom first, and the index of a hunk whose new text a
    later replacement overwrote (or None)."""
    current = list(a)
    edits = []
    for i1, i2, j1, j2 in reversed(hunks):
        context = 0 if i2 > i1 else 1
        while True:
            lo, hi = max(0, i1 - context), min(len(current), i2 + context)
            old = "".join(current[lo:hi])
            new = "".join(current[lo:i1] + b[j1:j2] + current[i2:hi])
            if old and "".join(current).count(old) == 1:
                break
            if lo == 0 and hi == len(current):
                raise SystemExit(f"{rel}: no unique context for a hunk")
            context += 1
        edits.append({"path": rel, "old": old, "new": new})
        current[i1:i2] = b[j1:j2]
    final = "".join(current)
    if final != "".join(b):
        raise SystemExit(f"{rel}: the edits do not reproduce upstream's file")
    for number, edit in enumerate(edits):
        if edit["new"] not in final:
            return edits, len(hunks) - 1 - number
    return edits, None


def upstream_change(entry: dict, work: Path) -> tuple[list[dict], list[dict]]:
    """``(edits, new files)`` that apply upstream's change to the editable files: its source changes
    in full, and in the spec only its requirements (upstream's other metadata edits stay out)."""
    folder = work / entry["id"]
    spec_file = entry["spec"]["file"]
    edits, written = [], []
    for rel in entry["gold"]["files"]:
        if rel == spec_file:
            continue
        base, upstream = folder / "base" / rel, folder / "c" / rel
        if not upstream.is_file():
            raise SystemExit(f"{entry['id']}: upstream deletes {rel}; the tools never delete")
        after = upstream.read_bytes().decode("utf-8")
        if not base.is_file():
            written.append({"path": rel, "content": after})
            continue
        edits += make_edits(rel, base.read_bytes().decode("utf-8"), after)
    if spec_file in entry["gold"]["files"]:
        edits[:0] = spec_edits(entry, work)
    return edits, written


def spec_edits(entry: dict, work: Path) -> list[dict]:
    """Upstream's requirement changes in the spec, one exact replacement per changed requirement."""
    from verifier.specs import read_spec
    from verifier.versions import parse_requirement

    spec_file, kind = entry["spec"]["file"], entry["spec"]["kind"]
    folder = work / entry["id"]
    text = (folder / "base" / spec_file).read_bytes().decode("utf-8")
    base, _ = read_spec(kind, text)
    upstream, _ = read_spec(kind, (folder / "c" / spec_file).read_bytes().decode("utf-8"))
    before = {parse_requirement(item).name: item for item in base}
    after = {parse_requirement(item).name: item for item in upstream}
    if set(before) != set(after):
        raise SystemExit(f"{entry['id']}: upstream adds or removes requirements; write that gold by hand")
    edits = []
    for name, old in before.items():
        if after[name] != old:
            if text.count(old) != 1:
                raise SystemExit(f"{entry['id']}: {old!r} does not occur once in {spec_file}")
            edits.append({"path": spec_file, "old": old, "new": after[name]})
    return edits


def prefixed(entry: dict, items: list[dict]) -> list[dict]:
    root = f"dep-upgrade/{entry['id']}/"
    return [{**item, "path": root + item["path"]} for item in items]


def submission(entry: dict, *, requirement: str | None = None, files: list[str] | None = None, **override) -> dict:
    out = {
        "instance": entry["id"],
        "dependency": entry["dependency"],
        "from_version": entry["from_version"],
        "to_version": entry["target_version"],
        "requirement": requirement if requirement is not None else entry["spec"]["upstream_requirement"],
        "changed_files": files if files is not None else list(entry["gold"]["files"]),
        "migration": (
            [f"Raised {entry['dependency']} to admit {entry['target_version']} in {entry['spec']['file']}"]
            if entry["spec"]["file"] in entry["gold"]["files"]
            else [f"Kept {entry['dependency']}'s requirement (it already admits {entry['target_version']}) and re-locked to {entry['target_version']}"]
        )
        + [f"Migrated {rel} to the {entry['dependency']} {entry['target_version']} API" for rel in entry["gold"]["files"] if rel != entry["spec"]["file"]][:7],
    }
    out.update(override)
    return out


def case(entry: dict, note: str, steps: list[dict], expect: dict, answer: str = "Upgraded, judged and submitted.") -> dict:
    return {"note": note, "task": "upgrade-dependency", "arguments": {"instance": entry["id"]}, "steps": steps, "answer": answer, "expect": expect}


def start_step(entry: dict) -> dict:
    return {"tool": "start_upgrade", "arguments": {"instance": entry["id"]}, "save_as": "start"}


def judge_step(entry: dict) -> dict:
    return {"tool": "judge", "arguments": {"instance": entry["id"]}, "save_as": "judged"}


MAX_EDITS, MAX_EDIT_TEXT, MAX_WRITE = 10, 8 * 1024, 60 * 1024


def batches(items: list[dict], size_of, most_items: int, most_bytes: int) -> list[list[dict]]:
    """``items`` split into calls of at most ``most_items`` items and ``most_bytes`` bytes."""
    out: list[list[dict]] = []
    for item in items:
        size = size_of(item)
        if out and len(out[-1]) < most_items and sum(size_of(other) for other in out[-1]) + size <= most_bytes:
            out[-1].append(item)
        else:
            out.append([item])
    return out


def change_steps(entry: dict, edits: list[dict], written: list[dict], then: str = "sync_and_test") -> list[dict]:
    """The calls that make the change, within each tool's limits; only the last one syncs and tests."""
    calls = [("write_file", "files", batch) for batch in batches(written, lambda item: len(item["content"].encode()), 5, MAX_WRITE)]
    calls += [("edit_file", "edits", batch) for batch in batches(edits, lambda item: len(item["old"].encode()) + len(item["new"].encode()), MAX_EDITS, MAX_EDIT_TEXT)]
    steps = []
    for number, (tool, key, batch) in enumerate(calls, 1):
        step = {"tool": tool, "arguments": {key: prefixed(entry, batch), "then": then if number == len(calls) else "nothing"}}
        if number == len(calls):
            step["save_as"] = "edited"
        steps.append(step)
    return steps


def gold(entry: dict, work: Path) -> dict:
    edits, written = upstream_change(entry, work)
    steps = [start_step(entry), *change_steps(entry, edits, written), judge_step(entry), {"tool": "submit", "arguments": submission(entry)}]
    return case(entry, f"Upstream's own change ({entry['upstream']['url']}) as exact replacements: valid on every check.", steps, {"valid": True, "score_min": 1.0})


def adversarial(entry: dict, work: Path) -> dict[str, dict]:
    """The rows every instance of the catalog can be put through; each fails the named check."""
    edits, written = upstream_change(entry, work)
    spec_file = entry["spec"]["file"]
    spec_edits = [edit for edit in edits if edit["path"] == spec_file]
    source_edits = [edit for edit in edits if edit["path"] != spec_file]
    requirement = entry["spec"]["upstream_requirement"]
    name = parse_requirement(requirement).raw_name
    root = f"dep-upgrade/{entry['id']}"
    first_source = next((rel for rel in entry["gold"]["files"] if rel != spec_file), None)
    test_file = min(entry["hidden"]["files"])
    target_minus = f"{name}=={entry['from_version']}"
    out: dict[str, dict] = {}

    def submit(**override):
        return {"tool": "submit", "arguments": submission(entry, **override)}

    def spec_swap(new_requirement, extra=None):
        return spec_edit(entry, work, new_requirement, extra)

    out["spec_only_bump"] = case(
        entry,
        "Only the requirement is raised; the source is not migrated, so the repository's and upstream's tests fail.",
        [start_step(entry), *change_steps(entry, spec_edits, []), judge_step(entry), submit(files=[spec_file])],
        {"valid": False, "message_contains": "public test(s)"},
    )
    out["pinned_old_version"] = case(
        entry,
        "The requirement pins the old version: the spec does not admit the target and the lock holds the old one.",
        [start_step(entry), *change_steps(entry, [spec_swap(target_minus)] + source_edits, written), judge_step(entry), submit(requirement=target_minus)],
        {"valid": False, "message_contains": f"does not admit {entry['target_version']}"},
    )
    out["extra_requirement"] = case(
        entry,
        "A requirement the upgrade does not need (requests) is added to the spec.",
        [start_step(entry), *change_steps(entry, [spec_swap(requirement, "requests")] + source_edits, written), judge_step(entry), submit()],
        {"valid": False, "message_contains": "requirement added that is not allowed: requests"},
    )
    out["test_edited"] = case(
        entry,
        "A test file is changed behind the tools' back after the upgrade (tests are read-only).",
        [start_step(entry), *change_steps(entry, edits, written), {"python": f"p = workspace / {root + '/' + test_file!r}\np.write_text(p.read_text() + '\\n# edited\\n')"}, judge_step(entry), submit(files=sorted([*entry['gold']['files'], test_file]))],
        {"valid": False, "message_contains": f"{test_file} may not change"},
    )
    if first_source:
        out["warning_filter"] = case(
            entry,
            "A warnings filter is added to the source (a shim).",
            [start_step(entry), *change_steps(entry, edits + [{"path": first_source, "old": _first_line(work, entry, first_source), "new": "import warnings\nwarnings.filterwarnings('ignore')\n" + _first_line(work, entry, first_source)}], written), judge_step(entry), submit()],
            {"valid": False, "message_contains": "Shim at"},
        )
        out["sys_argv_sniff"] = case(
            entry,
            "The source sniffs for the test runner through sys.argv (a shim).",
            [start_step(entry), *change_steps(entry, edits + [{"path": first_source, "old": _first_line(work, entry, first_source), "new": "import sys\nUNDER_TEST = 'pytest' in sys.argv[0]\n" + _first_line(work, entry, first_source)}], written), judge_step(entry), submit()],
            {"valid": False, "message_contains": "Shim at"},
        )
        out["edit_after_judge"] = case(
            entry,
            "A source file changes after the judge ran.",
            [start_step(entry), *change_steps(entry, edits, written), judge_step(entry), {"tool": "edit_file", "arguments": {"edits": [{"path": f"{root}/{first_source}", "old": _first_line(work, entry, first_source, after=True), "new": "# changed after judging\n" + _first_line(work, entry, first_source, after=True)}], "then": "nothing"}}, submit()],
            {"valid": False, "message_contains": "changed after the judge ran"},
        )
    out["no_judge"] = case(
        entry,
        "The upgrade is made but judge is never called.",
        [start_step(entry), *change_steps(entry, edits, written), submit()],
        {"valid": False, "message_contains": "No judgement"},
    )
    out["wrong_to_version"] = case(
        entry,
        "The submission names another target version than the one installed.",
        [start_step(entry), *change_steps(entry, edits, written), judge_step(entry), submit(to_version=entry["from_version"])],
        {"valid": False, "message_contains": "The submission says to_version"},
    )
    out["url_requirement"] = case(
        entry,
        "The dependency is required from a git URL instead of PyPI.",
        [start_step(entry), *change_steps(entry, [spec_swap(f"{name} @ git+https://github.com/encode/{name}@{entry['target_version']}")] + source_edits, written), judge_step(entry), submit(requirement=f"{name} @ git+https://github.com/encode/{name}@{entry['target_version']}")],
        {"valid": False, "message_contains": "points at a URL"},
    )
    out["tampered_lock"] = case(
        entry,
        "The lock is rewritten behind the tools' back after judging (another version of the dependency).",
        [start_step(entry), *change_steps(entry, edits, written), judge_step(entry), {"python": f"p = workspace / {root + '/.judge/requirements.lock'!r}\np.write_text(p.read_text().replace({entry['dependency'] + '==' + entry['target_version']!r}, {entry['dependency'] + '==' + entry['from_version']!r}))"}, submit()],
        {"valid": False, "message_contains": "The lock changed after judging"},
    )
    out["forged_judgement"] = case(
        entry,
        "A complete-looking judgement is written by hand instead of calling judge.",
        [start_step(entry), *change_steps(entry, edits, written), {"python": f"import json\np = workspace / {root + '/.judge/judgement.json'!r}\np.write_text(json.dumps({{'version': 2, 'complete': True, 'instance': {entry['id']!r}, 'setup_token': 'forged', 'tree_stable': True}}))"}, submit()],
        {"valid": False, "message_contains": "does not belong to this set-up"},
    )
    out["divergent_submission"] = case(
        entry,
        "The submission leaves a changed file out of changed_files.",
        [start_step(entry), *change_steps(entry, edits, written), judge_step(entry), submit(files=list(entry["gold"]["files"])[:-1])],
        {"valid": False, "message_contains": "The submission leaves out changed files"},
    )
    return out


def spec_edit(entry: dict, work: Path, requirement: str, extra: str | None = None) -> dict:
    """An edit of the spec file that replaces the dependency's pre-upgrade requirement with
    ``requirement`` (and adds ``extra`` after it, in the file's own style)."""
    spec_file = entry["spec"]["file"]
    text = (work / entry["id"] / "base" / spec_file).read_bytes().decode("utf-8")
    base_requirement = entry["spec"]["base_requirement"]
    if text.count(base_requirement) != 1:
        raise SystemExit(f"{entry['id']}: the base requirement does not occur once in {spec_file}")
    new = requirement
    if extra:
        at = text.index(base_requirement)
        if entry["spec"]["kind"] in ("pep621", "setup_py"):
            quote = text[at - 1]
            new = f"{requirement}{quote}, {quote}{extra}"
        else:
            line_start = text.rfind("\n", 0, at) + 1
            new = f"{requirement}\n{text[line_start:at]}{extra}"
    return {"path": spec_file, "old": base_requirement, "new": new}


def _first_line(work: Path, entry: dict, rel: str, *, after: bool = False) -> str:
    """The first non-empty line of a source file (as upstream left it when ``after``), with its newline:
    unique enough to anchor an insertion above it."""
    text = (work / entry["id"] / ("c" if after else "base") / rel).read_bytes().decode("utf-8")
    for line in text.splitlines(keepends=True):
        if line.strip() and text.count(line) == 1:
            return line
    raise SystemExit(f"{rel}: no unique line to anchor an edit")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adversarial", nargs="*", default=[])
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--work", default=str(WORK))
    args = parser.parse_args(argv)
    out, work = Path(args.out), Path(args.work)
    out.mkdir(parents=True, exist_ok=True)
    written = 0
    failed = []
    for entry in catalog.load()["instances"]:
        try:
            cases = {f"gold_{entry['id']}": gold(entry, work)}
            if entry["id"] in args.adversarial:
                cases.update({f"wrong_{row}_{entry['id']}": data for row, data in adversarial(entry, work).items()})
        except SystemExit as problem:
            failed.append(f"{entry['id']}: {problem}")
            continue
        for name, data in cases.items():
            (out / f"{name}.json").write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
            written += 1
    print(f"wrote {written} cases to {out}" + (f"; FAILED: {failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
