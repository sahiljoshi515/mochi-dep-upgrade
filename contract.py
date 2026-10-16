"""Each tool's and task's typed input and output (see nanoagent.plugin.contract): declarations only."""

from dataclasses import dataclass
from enum import Enum
from typing import Annotated

from slimconfig import Output


class Tool(Enum):
    PIN_UPGRADE = "pin_upgrade"
    START_UPGRADE = "start_upgrade"
    LIST_FILES = "list_files"
    READ_FILE = "read_file"
    SEARCH = "search"
    EDIT_FILE = "edit_file"
    WRITE_FILE = "write_file"
    SYNC = "sync"
    RUN_TESTS = "run_tests"
    JUDGE = "judge"


class Task(Enum):
    UPGRADE_DEPENDENCY = "upgrade-dependency"


class InstanceId(Enum):
    PYDANTIC_YAML_PYDANTIC_2 = "pydantic-yaml-pydantic-2"
    RESPX_HTTPX_0_28 = "respx-httpx-0.28"


class Then(Enum):
    NOTHING = "nothing"
    SYNC = "sync"
    SYNC_AND_TEST = "sync_and_test"


PATH = "A path relative to the workspace, e.g. dep-upgrade/<instance>/<package>/module.py"
TAIL = "The last lines of the command's output, at most 60 of at most 200 characters"
SECONDS = "How long the call took, in seconds"
COMPLETE = "Whether the work finished in this call; when false, call the tool again to continue"
NEXT = "What to do when complete is false, or empty"
VERSION = "A version, as PyPI names it, e.g. 0.28.1"


@dataclass
class UpgradeInput(Output):
    instance: Annotated[InstanceId, "The real upstream upgrade to redo: <project>-<dependency>-<new version line>"]


@dataclass
class PypiFile(Output):
    filename: Annotated[str, "A file PyPI serves for the target release"]
    sha256: Annotated[str, "Its sha256 as PyPI publishes it"]


@dataclass
class PinOutput(Output):
    instance: InstanceId
    catalog_sha256: Annotated[str, "sha256 of the instance's catalog entry the answer key was read from"]
    dependency: Annotated[str, "The distribution to upgrade, as PyPI names it"]
    from_version: Annotated[str, "The version locked before the upgrade"]
    target_version: Annotated[str, "The exact version the upgrade must lock"]
    pypi_files: Annotated[list[PypiFile], "What PyPI serves for the target release now, read when the task started"]
    pypi_yanked: Annotated[bool, "Whether PyPI marks the target release yanked"]
    prior_judgement_sha256: Annotated[str, "sha256 of a judgement already in the workspace when the task started, or empty"]


@dataclass
class Breaking(Output):
    test: Annotated[str, "A public test, as pytest names it"]
    error: Annotated[str, "Its first error line on the new version, before any code change"]


@dataclass
class StartOutput(Output):
    root: Annotated[str, "The project's folder in the workspace: dep-upgrade/<instance>"]
    complete: Annotated[bool, COMPLETE]
    next: Annotated[str, NEXT]
    repository: Annotated[str, "The upstream repository, owner/name, checked out at the commit before its upgrade"]
    dependency: Annotated[str, "The distribution to upgrade"]
    current_version: Annotated[str, "The version installed now (empty until the install is complete)"]
    target_version: Annotated[str, "The exact version to lock and install"]
    spec_file: Annotated[str, "The file that declares the project's requirements, relative to root"]
    current_requirement: Annotated[str, "The dependency's requirement as the spec states it now"]
    editable: Annotated[list[str], "What may change, as globs relative to root: the spec file and the package's source"]
    uses: Annotated[list[str], "Where the source imports the dependency, as path:line, at most 20"]
    breaking: Annotated[list[Breaking], "Public tests that fail on the new version before any code change, at most 10"]
    excluded_tests: Annotated[list[str], "Public tests that are not judged (they fail for reasons of their own), at most 20"]
    python: Annotated[str, "The Python version the project runs on"]
    fit: Annotated[str, "hosted when set-up and judging measured short enough for a hosted run, else local"]
    fit_note: Annotated[str, "What the fit means for this run"]
    rules: Annotated[list[str], "What may change, what may not, and how the work is judged"]


@dataclass
class ListInput(Output):
    path: Annotated[str, "A folder, relative to the workspace, e.g. dep-upgrade/<instance>"]
    max_entries: Annotated[int, "At most this many entries, 1 to 200"]


@dataclass
class Entry(Output):
    path: Annotated[str, PATH]
    kind: Annotated[str, "file or dir"]
    size: Annotated[int, "Bytes, for a file"]


@dataclass
class ListOutput(Output):
    path: str
    entries: Annotated[list[Entry], "Files and folders under path, recursively, sorted"]
    total: Annotated[int, "How many entries there are in all"]
    truncated: Annotated[bool, "Whether entries stops short of total"]


@dataclass
class ReadInput(Output):
    path: Annotated[str, PATH]
    start_line: Annotated[int, "The first line to return, counting from 1"]
    max_lines: Annotated[int, "At most this many lines, 1 to 200 (and at most 8 KB of text)"]


@dataclass
class ReadOutput(Output):
    path: str
    start_line: int
    lines: Annotated[list[str], "The lines, without their line breaks"]
    total_lines: Annotated[int, "How many lines the file has"]
    truncated: Annotated[bool, "Whether fewer lines than asked came back to stay under 8 KB; continue from start_line + len(lines)"]


@dataclass
class SearchInput(Output):
    path: Annotated[str, "The folder to search, relative to the workspace"]
    pattern: Annotated[str, "A Python regular expression, matched against each line"]
    glob: Annotated[str, "Which files to search, by name, e.g. *.py"]
    max_hits: Annotated[int, "At most this many hits, 1 to 50"]


@dataclass
class Hit(Output):
    path: Annotated[str, PATH]
    line: Annotated[int, "The line number, counting from 1"]
    text: Annotated[str, "The line, trimmed to 200 characters"]


@dataclass
class SearchOutput(Output):
    hits: list[Hit]
    files_searched: int
    truncated: Annotated[bool, "Whether more lines matched than were returned"]


@dataclass
class SyncOutput(Output):
    ok: Annotated[bool, "Whether the spec resolved and the environment was installed"]
    complete: Annotated[bool, COMPLETE]
    next: Annotated[str, NEXT]
    requirement: Annotated[str, "The dependency's requirement as the spec states it"]
    locked_version: Annotated[str, "The dependency's version in the new lock, or empty"]
    installed_version: Annotated[str, "The dependency's version installed now, or empty"]
    changes: Annotated[list[str], "Packages whose locked version differs from before the upgrade, as name old -> new"]
    tail: Annotated[list[str], TAIL]
    seconds: Annotated[float, SECONDS]


@dataclass
class TestsInput(Output):
    instance: Annotated[InstanceId, "The instance whose public tests to run"]
    tests: Annotated[list[str], "Test files or node ids relative to root, e.g. tests/test_api.py; [] for all"]


@dataclass
class TestsOutput(Output):
    command: Annotated[str, "The pytest command line, without paths"]
    exit_code: int
    collected: int
    passed: int
    failed: int
    errors: int
    skipped: int
    failed_ids: Annotated[list[str], "Judged tests that failed or errored, at most 30"]
    excluded_failures: Annotated[int, "Failures among the tests that are not judged (ignore them)"]
    tail: Annotated[list[str], TAIL]
    seconds: Annotated[float, SECONDS]


@dataclass
class Edit(Output):
    path: Annotated[str, "A file relative to the workspace: the spec file or a source file the start listed as editable"]
    old: Annotated[str, "Text that occurs exactly once in the file now (include enough lines to make it unique)"]
    new: Annotated[str, "What replaces it"]


@dataclass
class EditInput(Output):
    edits: Annotated[list[Edit], "1 to 10 replacements, applied in order; all apply or none (at most 8 KB of text in all)"]
    then: Annotated[Then, "After editing: nothing, sync (re-lock and install), or sync_and_test (also run the public tests)"]


@dataclass
class Edited(Output):
    path: str
    replacements: Annotated[int, "How many of the edits changed this file"]
    bytes: Annotated[int, "The file's size afterwards"]


@dataclass
class EditOutput(Output):
    edited: Annotated[list[Edited], "Each changed file, in the order first edited"]
    sync: Annotated[SyncOutput | None, "The sync's result, when then asked for it"]
    tests: Annotated[TestsOutput | None, "The public tests' result, when then asked for it and the sync succeeded"]


@dataclass
class FileWrite(Output):
    path: Annotated[str, "A file relative to the workspace: the spec file or a source file under an editable glob"]
    content: Annotated[str, "The whole file's new text"]


@dataclass
class WriteInput(Output):
    files: Annotated[list[FileWrite], "1 to 5 files, at most 60 KB in all; every file is written, or none"]
    then: Annotated[Then, "After writing: nothing, sync, or sync_and_test"]


@dataclass
class Written(Output):
    path: str
    bytes: int


@dataclass
class WriteOutput(Output):
    written: Annotated[list[Written], "Each file written, in the order given"]
    sync: Annotated[SyncOutput | None, "The sync's result, when then asked for it"]
    tests: Annotated[TestsOutput | None, "The public tests' result, when then asked for it and the sync succeeded"]


@dataclass
class JudgeOutput(Output):
    recorded: Annotated[bool, "Whether the judgement was written (only when complete)"]
    complete: Annotated[bool, COMPLETE]
    next: Annotated[str, NEXT]
    changed_files: Annotated[list[str], "Every file that differs from the project before the upgrade, relative to root"]
    requirement: Annotated[str, "The dependency's requirement as the spec states it"]
    locked_version: Annotated[str, "The dependency's version in the judged lock"]
    installed_version: Annotated[str, "The dependency's version installed for judging"]
    build_ok: bool
    public_passed: Annotated[int, "Judged public tests that passed"]
    public_failed: Annotated[int, "Judged public tests that did not pass"]
    violations: Annotated[list[str], "Shims found in the added lines, as file:line: pattern"]
    seconds: Annotated[float, SECONDS]


@dataclass
class UpgradeReportOutput(Output):
    instance: Annotated[InstanceId, "The instance upgraded"]
    dependency: Annotated[str, "The distribution upgraded"]
    from_version: Annotated[str, VERSION]
    to_version: Annotated[str, "The version now locked and installed"]
    requirement: Annotated[str, "The dependency's requirement as the spec now states it"]
    changed_files: Annotated[list[str], "Every file you changed, relative to the project root"]
    migration: Annotated[list[str], "1 to 8 notes of 10 to 200 characters, one per change made for the new version"]


TOOLS = {
    Tool.PIN_UPGRADE: (UpgradeInput, PinOutput),
    Tool.START_UPGRADE: (UpgradeInput, StartOutput),
    Tool.LIST_FILES: (ListInput, ListOutput),
    Tool.READ_FILE: (ReadInput, ReadOutput),
    Tool.SEARCH: (SearchInput, SearchOutput),
    Tool.EDIT_FILE: (EditInput, EditOutput),
    Tool.WRITE_FILE: (WriteInput, WriteOutput),
    Tool.SYNC: (UpgradeInput, SyncOutput),
    Tool.RUN_TESTS: (TestsInput, TestsOutput),
    Tool.JUDGE: (UpgradeInput, JudgeOutput),
}
TASKS = {Task.UPGRADE_DEPENDENCY: (UpgradeInput, UpgradeReportOutput)}
