"""Reading and writing the project: listings, reads and searches anywhere in the workspace but
``.judge/``; writes only to ``pyproject.toml``'s dependencies and the package's own ``.py`` files,
several files per call, all or none."""

from __future__ import annotations

import ast
import fnmatch
import re
import tomllib
from pathlib import Path

from contract import (
    Entry,
    Hit,
    ListInput,
    ListOutput,
    ProjectId,
    ReadInput,
    ReadOutput,
    SearchInput,
    SearchOutput,
    WriteInput,
    WriteOutput,
    Written,
)
from plugin.common import JUDGE_DIR, MAX_LINE, TOOL_DIRS, WORKSPACE_PREFIX, ToolError, confine, workspace_relative
from plugin.instances import load_instance
from plugin.project import READY
from verifier.pyproject import blank_dependencies, dependencies
from verifier.versions import parse_requirement

MAX_ENTRIES = 200
MAX_LINES = 200
MAX_READ_BYTES = 8 * 1024
MAX_HITS = 50
MAX_FILES = 5
MAX_WRITE = 60 * 1024
MAX_READ = 2 * 1024 * 1024
MAX_SEARCH_FILES = 3000
# Names a written file may not have: pytest would load them, or they are not source.
FORBIDDEN_NAMES = frozenset({"conftest.py", "pytest.ini", "setup.py", "setup.cfg", "tox.ini"})


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def _inside_tool_dir(relative: Path) -> bool:
    return bool(TOOL_DIRS & set(relative.parts))


def list_files(given: ListInput, workspace: Path) -> ListOutput:
    folder = confine(workspace, given.path)
    if not folder.is_dir():
        raise ToolError(f"not a folder: {given.path}")
    limit = _clamp(given.max_entries, 1, MAX_ENTRIES)
    entries: list[Entry] = []
    total = 0
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(folder)
        if _inside_tool_dir(relative) or path.suffix == ".pyc" or path.is_symlink():
            continue
        total += 1
        if len(entries) < limit:
            entries.append(
                Entry(
                    path=workspace_relative(workspace, path),
                    kind="dir" if path.is_dir() else "file",
                    size=path.stat().st_size if path.is_file() else 0,
                )
            )
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
    """``lines`` cut to at most ``most_bytes`` of UTF-8 text (one line at least, itself cut);
    returns them and whether anything was left out."""
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
    window = lines[start - 1 : start - 1 + count]
    kept, cut = cap_lines(window)
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
        if _inside_tool_dir(relative) or path.is_symlink() or not path.is_file() or path.suffix == ".pyc":
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


def writable_target(workspace: Path, rel: str) -> tuple[Path, str, str]:
    """``(path, project id, project-relative path)`` for a path write_file may write, or raise."""
    path = confine(workspace, rel)
    relative = Path(workspace_relative(workspace, path))
    parts = relative.parts
    projects = {member.value for member in ProjectId}
    if len(parts) < 3 or parts[0] != WORKSPACE_PREFIX or parts[1] not in projects:
        raise ToolError(f"write_file only writes inside {WORKSPACE_PREFIX}/<project>/: {rel}")
    project = parts[1]
    root = workspace.resolve() / WORKSPACE_PREFIX / project
    if not (root / JUDGE_DIR / READY).is_file():
        raise ToolError(f"start_project {project} first")
    inside = Path(*parts[2:]).as_posix()
    package = load_instance(project).package
    if inside == "pyproject.toml":
        return path, project, inside
    if not inside.startswith(f"src/{package}/") or not inside.endswith(".py"):
        raise ToolError(f"only pyproject.toml and .py files under src/{package}/ may be written: {rel}")
    if any(part.startswith(".") for part in parts[2:]) or path.name in FORBIDDEN_NAMES:
        raise ToolError(f"that file name may not be written: {rel}")
    return path, project, inside


def _check_pyproject(content: str, pristine: str) -> None:
    try:
        tomllib.loads(content)
    except tomllib.TOMLDecodeError as error:
        raise ToolError(f"pyproject.toml is not valid TOML: {error}") from error
    if blank_dependencies(content) != blank_dependencies(pristine):
        raise ToolError("only the [project] dependencies array of pyproject.toml may change")
    try:
        entries = dependencies(content)
        for entry in entries:
            parse_requirement(entry)
    except ValueError as error:
        raise ToolError(f"pyproject.toml dependencies are not readable requirements: {error}") from error


def write_file(given: WriteInput, workspace: Path) -> WriteOutput:
    """Write 1 to 5 files in one call. Every file is checked first (path, size, TOML or Python
    syntax, the pyproject rule); if any is refused nothing is written."""
    if not 1 <= len(given.files) <= MAX_FILES:
        raise ToolError(f"write 1 to {MAX_FILES} files per call")
    if len({item.path for item in given.files}) != len(given.files):
        raise ToolError("a path is given twice")
    total = 0
    planned: list[tuple[Path, bytes, str]] = []
    for item in given.files:
        data = item.content.encode("utf-8")
        total += len(data)
        if "\0" in item.content:
            raise ToolError(f"content must be text: {item.path}")
        path, project, inside = writable_target(workspace, item.path)
        if inside == "pyproject.toml":
            pristine = (load_instance(project).project_dir / "pyproject.toml").read_text(encoding="utf-8")
            _check_pyproject(item.content, pristine)
        else:
            try:
                ast.parse(item.content, filename=inside)
            except SyntaxError as error:
                raise ToolError(f"{inside} would not be valid Python: line {error.lineno}: {error.msg}") from error
        planned.append((path, data, item.path))
    if total > MAX_WRITE:
        raise ToolError(f"the files hold {total} bytes, over the {MAX_WRITE}-byte limit per call")
    written: list[Written] = []
    for path, data, rel in planned:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        written.append(Written(path=rel, bytes=len(data)))
    return WriteOutput(written=written)
