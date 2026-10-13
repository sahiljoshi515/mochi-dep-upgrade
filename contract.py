"""Each tool's and task's typed input and output (see nanoagent.plugin.contract): declarations only."""

from dataclasses import dataclass
from enum import Enum
from typing import Annotated

from slimconfig import Output


class Tool(Enum):
    PIN_PROJECT = "pin_project"
    START_PROJECT = "start_project"
    LIST_FILES = "list_files"
    READ_FILE = "read_file"
    SEARCH = "search"
    WRITE_FILE = "write_file"
    SYNC = "sync"
    RUN_BUILD = "run_build"
    RUN_TESTS = "run_tests"
    JUDGE = "judge"


class Task(Enum):
    UPGRADE_DEPENDENCY = "upgrade-dependency"


class ProjectId(Enum):
    INVOICER_PYDANTIC_2 = "invoicer-pydantic-2"
    LEDGER_SQLALCHEMY_2 = "ledger-sqlalchemy-2"
    NOTES_FLASK_3 = "notes-flask-3"
    SALESREPORT_PANDAS_3 = "salesreport-pandas-3"
    ARRAYS_NUMPY_2 = "arrays-numpy-2"


PATH = "A path relative to the workspace, e.g. dep-upgrade/<project>/src/<package>/models.py"
SHA = "A sha256 digest, 64 hex characters"
TAIL = "The last lines of the command's output, at most 60 of at most 200 characters"
SECONDS = "How long the call took, in seconds"
COMPLETE = "Whether the work finished in this call; when false, call the tool again to continue"
NEXT = "What to do when complete is false, or empty"


@dataclass
class UpgradeInput(Output):
    project: Annotated[ProjectId, "The project to upgrade"]


@dataclass
class PinOutput(Output):
    project: ProjectId
    dependency: Annotated[str, "The distribution to upgrade, as PyPI names it"]
    package: Annotated[str, "The project's package folder under src/"]
    from_spec: Annotated[str, "The requirement the pristine project states for the dependency"]
    from_version: Annotated[str, "The dependency's version locked before the upgrade"]
    target_version: Annotated[str, "The exact version the upgrade must lock"]
    requires_python: Annotated[str, "The project's requires-python, which may not change"]
    pristine_tree_sha256: Annotated[str, "Tree hash of the whole pristine project"]
    protected_tree_sha256: Annotated[str, "Tree hash of tests/** and README.md, which may not change"]
    pyproject_sha256: Annotated[str, "sha256 of the pristine pyproject.toml"]
    pyproject_rest_sha256: Annotated[str, "sha256 of pyproject.toml with its [project] dependencies array blanked"]
    pristine_dependencies: Annotated[list[str], "The pristine [project] dependencies, as written"]
    other_dependencies: Annotated[dict[str, str], "Every other direct dependency's locked version, by name"]
    allowed_new_dependencies: Annotated[list[str], "Distributions the upgrade may add to [project] dependencies"]
    allowed_collateral: Annotated[list[str], "Direct dependencies whose requirement and locked version may change"]
    forbidden_patterns: Annotated[list[str], "Regular expressions no file under src/ may match"]
    hidden_tests_sha256: Annotated[str, "Tree hash of the hidden tests"]
    hidden_test_ids: Annotated[list[str], "Every hidden test, as pytest names it"]
    max_new_files: Annotated[int, "How many new files the upgrade may add under src/"]
    max_added_lines: Annotated[int, "How many lines the upgrade may add in all"]


@dataclass
class StartOutput(Output):
    root: Annotated[str, "The project's folder in the workspace: dep-upgrade/<project>"]
    complete: Annotated[bool, COMPLETE]
    next: Annotated[str, NEXT]
    dependency: Annotated[str, "The distribution to upgrade"]
    current_version: Annotated[str, "The version installed now (empty until the install is complete)"]
    target_version: Annotated[str, "The exact version to lock and install"]
    package: Annotated[str, "The project's package folder under root/src"]
    uses_dependency: Annotated[list[str], "The source files that import the dependency (or its collateral), relative to root; read these first"]
    layout: Annotated[list[str], "The project's files, relative to root, at most 40"]
    allowed_new_dependencies: Annotated[list[str], "Distributions that may be added to [project] dependencies"]
    allowed_collateral: Annotated[list[str], "Other direct dependencies whose requirement may change"]
    rules: Annotated[list[str], "What may change, what may not, and how the work is judged"]
    build_hint: Annotated[str, "How the project is built"]
    test_hint: Annotated[str, "How the tests are run"]


@dataclass
class ListInput(Output):
    path: Annotated[str, "A folder, relative to the workspace, e.g. dep-upgrade/<project>/src"]
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
    glob: Annotated[str, "Which files to search, by name, e.g. *.py or *.toml"]
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
class FileWrite(Output):
    path: Annotated[str, "dep-upgrade/<project>/pyproject.toml or a .py file under dep-upgrade/<project>/src/<package>/"]
    content: Annotated[str, "The whole file's new text"]


@dataclass
class WriteInput(Output):
    files: Annotated[list[FileWrite], "1 to 5 files, at most 60 KB in all; every file is written, or none"]


@dataclass
class Written(Output):
    path: str
    bytes: int


@dataclass
class WriteOutput(Output):
    written: Annotated[list[Written], "Each file written, in the order given"]


@dataclass
class SyncOutput(Output):
    ok: Annotated[bool, "Whether the lock resolved and the environment was installed"]
    complete: Annotated[bool, COMPLETE]
    next: Annotated[str, NEXT]
    installed: Annotated[dict[str, str], "Each direct dependency's installed version"]
    tail: Annotated[list[str], TAIL]
    seconds: Annotated[float, SECONDS]


@dataclass
class BuildOutput(Output):
    ok: Annotated[bool, "Whether the wheel was built"]
    wheel: Annotated[str, "The wheel's file name, or empty"]
    tail: Annotated[list[str], TAIL]
    seconds: Annotated[float, SECONDS]


@dataclass
class TestsInput(Output):
    project: Annotated[ProjectId, "The project whose public tests to run"]
    tests: Annotated[list[str], "Test files or node ids relative to root, e.g. tests/test_models.py; [] for all"]


@dataclass
class TestsOutput(Output):
    command: Annotated[str, "The pytest command line, without paths"]
    exit_code: int
    collected: int
    passed: int
    failed: int
    errors: int
    skipped: int
    failed_ids: Annotated[list[str], "The tests that failed or errored, at most 50"]
    tail: Annotated[list[str], TAIL]
    seconds: Annotated[float, SECONDS]


@dataclass
class JudgeOutput(Output):
    recorded: Annotated[bool, "Whether the judgement was written (only when complete)"]
    complete: Annotated[bool, COMPLETE]
    next: Annotated[str, NEXT]
    changed_files: Annotated[list[str], "Every file that differs from the pristine project, relative to root"]
    protected_changes: Annotated[list[str], "Changed files that may not change: tests/**, README.md"]
    lock_ok: Annotated[bool, "Whether uv.lock matches pyproject.toml"]
    installed_version: Annotated[str, "The dependency's installed version"]
    build_ok: bool
    public_passed: int
    public_failed: int
    violations: Annotated[list[str], "Forbidden patterns found under src/, as file:line"]
    seconds: Annotated[float, SECONDS]


TOOLS = {
    Tool.PIN_PROJECT: (UpgradeInput, PinOutput),
    Tool.START_PROJECT: (UpgradeInput, StartOutput),
    Tool.LIST_FILES: (ListInput, ListOutput),
    Tool.READ_FILE: (ReadInput, ReadOutput),
    Tool.SEARCH: (SearchInput, SearchOutput),
    Tool.WRITE_FILE: (WriteInput, WriteOutput),
    Tool.SYNC: (UpgradeInput, SyncOutput),
    Tool.RUN_BUILD: (UpgradeInput, BuildOutput),
    Tool.RUN_TESTS: (TestsInput, TestsOutput),
    Tool.JUDGE: (UpgradeInput, JudgeOutput),
}
TASKS = {Task.UPGRADE_DEPENDENCY: UpgradeInput}
