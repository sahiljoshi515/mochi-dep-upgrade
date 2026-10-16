"""Reading and changing the project: listings, reads and searches anywhere in the workspace but
``.judge/``; edits (exact replacements) and whole-file writes only to the instance's spec file and to
source files under its editable globs, all or none per call, optionally followed by a sync and a run
of the public tests."""

from __future__ import annotations

import ast
import fnmatch
import re
from pathlib import Path

from contract import (
    Edited,
    EditInput,
    EditOutput,
    Entry,
    Hit,
    ListInput,
    ListOutput,
    ReadInput,
    ReadOutput,
    SearchInput,
    SearchOutput,
    TestsInput,
    Then,
    UpgradeInput,
    WriteInput,
    WriteOutput,
    Written,
)
from plugin.common import (
    JUDGE_DIR,
    MAX_LINE,
    WORKSPACE_PREFIX,
    Budget,
    ToolError,
    check_workspace_sizes,
    confine,
    workspace_relative,
)
from plugin.project import PRISTINE_DIR, is_editable, ready_root
from plugin.spec import read as read_spec
from verifier.trees import SKIP

MAX_ENTRIES = 200
MAX_LINES = 200
MAX_READ_BYTES = 8 * 1024
MAX_HITS = 50
MAX_FILES = 5
MAX_WRITE = 60 * 1024
MAX_EDITS = 10
MAX_EDIT_TEXT = 8 * 1024
MAX_READ = 2 * 1024 * 1024
MAX_SEARCH_FILES = 3000
# Names a written file may not have: pytest or the build would load them as configuration.
FORBIDDEN_NAMES = frozenset({"conftest.py", "pytest.ini", "tox.ini", "setup.cfg", "sitecustomize.py", "usercustomize.py"})


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def _hidden(relative: Path) -> bool:
    return bool(SKIP & set(relative.parts)) or relative.suffix == ".pyc"


def list_files(given: ListInput, workspace: Path) -> ListOutput:
    folder = confine(workspace, given.path)
    if not folder.is_dir():
        raise ToolError(f"not a folder: {given.path}")
    limit = _clamp(given.max_entries, 1, MAX_ENTRIES)
    entries: list[Entry] = []
    total = 0
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(folder)
        if _hidden(relative) or path.is_symlink():
            continue
        total += 1
        if len(entries) < limit:
            entries.append(Entry(path=workspace_relative(workspace, path), kind="dir" if path.is_dir() else "file", size=path.stat().st_size if path.is_file() else 0))
    return ListOutput(path=given.path, entries=entries, total=total, truncated=total > len(entries))


def _text_of(path: Path, rel: str) -> str:
    if not path.is_file():
        raise ToolError(f"not a file: {rel}")
    if path.stat().st_size > MAX_READ:
        raise ToolError(f"file is too large to read: {rel}")
    data = path.read_bytes()
    if b"\0" in data:
        raise ToolError(f"not a text file: {rel}")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ToolError(f"not UTF-8 text: {rel}") from error


def cap_lines(lines: list[str], most_bytes: int = MAX_READ_BYTES) -> tuple[list[str], bool]:
    """``lines`` cut to at most ``most_bytes`` of UTF-8 text (one line at least, itself cut)."""
    kept: list[str] = []
    size = 0
    for line in lines:
        cost = len(line.encode("utf-8")) + 1
        if kept and size + cost > most_bytes:
            return kept, True
        if not kept and cost > most_bytes:
            return [line.encode("utf-8")[: most_bytes - 1].decode("utf-8", errors="ignore")], True
        kept.append(line)
        size += cost
    return kept, False


def read_file(given: ReadInput, workspace: Path) -> ReadOutput:
    path = confine(workspace, given.path)
    lines = _text_of(path, given.path).splitlines()
    start = _clamp(given.start_line, 1, max(1, len(lines)))
    count = _clamp(given.max_lines, 1, MAX_LINES)
    kept, cut = cap_lines(lines[start - 1 : start - 1 + count])
    return ReadOutput(path=given.path, start_line=start, lines=kept, total_lines=len(lines), truncated=cut)


def search(given: SearchInput, workspace: Path) -> SearchOutput:
    folder = confine(workspace, given.path)
    if not folder.is_dir():
        raise ToolError(f"not a folder: {given.path}")
    try:
        pattern = re.compile(given.pattern)
    except re.error as error:
        raise ToolError(f"not a valid regular expression: {error}") from error
    glob = given.glob.strip() or "*"
    limit = _clamp(given.max_hits, 1, MAX_HITS)
    hits: list[Hit] = []
    searched = 0
    truncated = False
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(folder)
        if _hidden(relative) or path.is_symlink() or not path.is_file():
            continue
        if not (fnmatch.fnmatch(path.name, glob) or fnmatch.fnmatch(relative.as_posix(), glob)):
            continue
        if searched >= MAX_SEARCH_FILES:
            truncated = True
            break
        searched += 1
        if path.stat().st_size > MAX_READ:
            continue
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            continue
        if "\0" in text:
            continue
        shown = workspace_relative(workspace, path)
        for number, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                if len(hits) >= limit:
                    truncated = True
                    break
                hits.append(Hit(path=shown, line=number, text=line.strip()[:MAX_LINE]))
        if truncated:
            break
    return SearchOutput(hits=hits, files_searched=searched, truncated=truncated)


# ----- changing the project -----


def target(workspace: Path, rel: str) -> tuple[Path, Path, dict, str]:
    """``(path, root, catalog entry, project-relative path)`` for a file the agent may change, or raise."""
    path = confine(workspace, rel)
    parts = Path(workspace_relative(workspace, path)).parts
    if len(parts) < 3 or parts[0] != WORKSPACE_PREFIX:
        raise ToolError(f"only files inside {WORKSPACE_PREFIX}/<instance>/ may change: {rel}")
    root, entry = ready_root(workspace, parts[1])
    inside = Path(*parts[2:]).as_posix()
    if any(part.startswith(".") for part in parts[2:]) or path.name in FORBIDDEN_NAMES:
        raise ToolError(f"that file may not change: {rel}")
    if not is_editable(entry, inside):
        raise ToolError(f"{inside} may not change: only {entry['spec']['file']} and {', '.join(entry['source_globs'])}")
    return path, root, entry, inside


def check_content(root: Path, entry: dict, inside: str, text: str) -> None:
    """Refuse content the project could not use: invalid Python, or a spec that cannot be read or
    changes anything but its requirements."""
    if "\0" in text:
        raise ToolError(f"content must be text: {inside}")
    if inside == entry["spec"]["file"]:
        kind = entry["spec"]["kind"]
        _, blanked = read_spec(kind, text, name=inside)
        pristine = (root / JUDGE_DIR / PRISTINE_DIR / inside).read_bytes().decode("utf-8")
        _, pristine_blanked = read_spec(kind, pristine, name=inside)
        if blanked != pristine_blanked:
            raise ToolError(f"only the requirements in {inside} may change; the rest of the file must stay as it was")
    if inside.endswith(".py"):
        try:
            ast.parse(text, filename=inside)
        except SyntaxError as error:
            raise ToolError(f"{inside} would not be valid Python: line {error.lineno}: {error.msg}") from error


def _then(workspace: Path, roots: set[str], then: Then):
    """Run what ``then`` asks for after a change: (sync output, tests output)."""
    if then == Then.NOTHING:
        return None, None
    from contract import InstanceId
    from plugin.sync import run_tests, sync

    if len(roots) != 1:
        raise ToolError("then needs every change in one instance")
    instance = InstanceId(next(iter(roots)))
    budget = Budget()
    synced = sync(UpgradeInput(instance=instance), workspace, budget=budget)
    if then == Then.SYNC or not (synced.ok and synced.complete):
        return synced, None
    return synced, run_tests(TestsInput(instance=instance, tests=[]), workspace, budget=budget)


def edit_file(given: EditInput, workspace: Path) -> EditOutput:
    """Apply 1 to 10 exact replacements in order: each ``old`` must occur exactly once in its file
    as it stands then. Every resulting file is checked before any is written; then optionally sync
    and test."""
    if not 1 <= len(given.edits) <= MAX_EDITS:
        raise ToolError(f"give 1 to {MAX_EDITS} edits per call")
    if sum(len(edit.old.encode("utf-8")) + len(edit.new.encode("utf-8")) for edit in given.edits) > MAX_EDIT_TEXT:
        raise ToolError(f"the edits hold over {MAX_EDIT_TEXT} bytes of text; split them over calls")
    staged: dict[Path, list] = {}
    order: list[Path] = []
    for number, edit in enumerate(given.edits, 1):
        path, root, entry, inside = target(workspace, edit.path)
        if path not in staged:
            if not path.is_file():
                raise ToolError(f"edit {number}: {inside} does not exist; write_file creates new files")
            try:
                current = path.read_bytes().decode("utf-8")
            except UnicodeDecodeError as error:
                raise ToolError(f"edit {number}: {inside} is not UTF-8 text") from error
            staged[path] = [current, 0, root, entry, inside, edit.path]
            order.append(path)
        text = staged[path][0]
        if not edit.old:
            raise ToolError(f"edit {number}: old must not be empty")
        found = text.count(edit.old)
        if found != 1:
            raise ToolError(f"edit {number}: old occurs {found} times in {inside}; it must occur exactly once (add surrounding lines)")
        staged[path][0] = text.replace(edit.old, edit.new, 1)
        staged[path][1] += 1
    for path in order:
        text, _, root, entry, inside, _ = staged[path]
        check_content(root, entry, inside, text)
    edited = []
    roots = set()
    for path in order:
        text, count, root, entry, inside, rel = staged[path]
        path.write_bytes(text.encode("utf-8"))
        edited.append(Edited(path=rel, replacements=count, bytes=len(text.encode("utf-8"))))
        roots.add(entry["id"])
        check_workspace_sizes(root)
    synced, tests = _then(workspace, roots, given.then)
    return EditOutput(edited=edited, sync=synced, tests=tests)


def write_file(given: WriteInput, workspace: Path) -> WriteOutput:
    """Write 1 to 5 whole files (new or replaced), all or none; then optionally sync and test."""
    if not 1 <= len(given.files) <= MAX_FILES:
        raise ToolError(f"write 1 to {MAX_FILES} files per call")
    if len({item.path for item in given.files}) != len(given.files):
        raise ToolError("a path is given twice")
    total = 0
    planned = []
    for item in given.files:
        total += len(item.content.encode("utf-8"))
        path, root, entry, inside = target(workspace, item.path)
        check_content(root, entry, inside, item.content)
        planned.append((path, item, root, entry))
    if total > MAX_WRITE:
        raise ToolError(f"the files hold {total} bytes, over the {MAX_WRITE}-byte limit per call")
    written = []
    roots = set()
    for path, item, root, entry in planned:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(item.content.encode("utf-8"))
        written.append(Written(path=item.path, bytes=len(item.content.encode("utf-8"))))
        roots.add(entry["id"])
        check_workspace_sizes(root)
    synced, tests = _then(workspace, roots, given.then)
    return WriteOutput(written=written, sync=synced, tests=tests)
