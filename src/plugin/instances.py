"""The shipped projects: ``src/plugin/instances/<project>/{project/, hidden_tests/, instance.json,
solution.patch}``. ``instance.json`` says what the upgrade is and how it is judged."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

INSTANCES = Path(__file__).with_name("instances")


@dataclass(frozen=True)
class Instance:
    id: str
    title: str
    dependency: str
    import_name: str
    package: str
    from_spec: str
    from_version: str
    target_version: str
    allowed_new_dependencies: tuple[str, ...]
    allowed_collateral: tuple[str, ...]
    forbidden_patterns: tuple[str, ...]
    warning_flags: tuple[str, ...]
    hidden_test_ids: tuple[str, ...]
    max_new_files: int
    max_added_lines: int
    build_hint: str
    test_hint: str
    notes: tuple[str, ...]

    @property
    def root(self) -> Path:
        return INSTANCES / self.id

    @property
    def project_dir(self) -> Path:
        return self.root / "project"

    @property
    def hidden_dir(self) -> Path:
        return self.root / "hidden_tests"

    @property
    def solution_patch(self) -> Path:
        return self.root / "solution.patch"


def load_instance(project: str) -> Instance:
    path = INSTANCES / project / "instance.json"
    if not path.is_file():
        raise ValueError(f"unknown project {project!r}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return Instance(
        id=data["id"],
        title=data["title"],
        dependency=data["dependency"],
        import_name=data["import_name"],
        package=data["package"],
        from_spec=data["from_spec"],
        from_version=data["from_version"],
        target_version=data["target_version"],
        allowed_new_dependencies=tuple(data.get("allowed_new_dependencies", [])),
        allowed_collateral=tuple(data.get("allowed_collateral", [])),
        forbidden_patterns=tuple(data["forbidden_patterns"]),
        warning_flags=tuple(data["warning_flags"]),
        hidden_test_ids=tuple(data["hidden_test_ids"]),
        max_new_files=int(data.get("max_new_files", 5)),
        max_added_lines=int(data.get("max_added_lines", 600)),
        build_hint=data["build_hint"],
        test_hint=data["test_hint"],
        notes=tuple(data.get("notes", [])),
    )


def all_instances() -> list[Instance]:
    return [load_instance(path.name) for path in sorted(INSTANCES.iterdir()) if (path / "instance.json").is_file()]
