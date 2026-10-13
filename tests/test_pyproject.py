"""The verifier's regex readers for pyproject.toml and uv.lock, against tomllib where it applies."""

from __future__ import annotations

import tomllib

import pytest

from verifier.pyproject import (
    blank_dependencies,
    dependencies,
    is_project,
    is_pypi,
    lock_packages,
    parse_string_array,
    requires_python,
    table_span,
)

PYPROJECT = '''[build-system]
requires = ["hatchling>=1.25"]
build-backend = "hatchling.build"

[project]
name = "invoicer"
version = "1.4.0"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=1.10.13,<2",  # the old major
    'click[extra]>=8', "requests ; python_version < \\"4\\"",
]

[project.optional-dependencies]
docs = ["sphinx"]

[dependency-groups]
dev = [
    "pytest>=8",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
'''

LOCK = '''version = 1
revision = 3
requires-python = ">=3.12"

[[package]]
name = "invoicer"
version = "1.4.0"
source = { editable = "." }
dependencies = [
    { name = "pydantic" },
]

[package.metadata]
requires-dist = [{ name = "pydantic", specifier = ">=1.10.13,<2" }]

[[package]]
name = "pydantic"
version = "1.10.13"
source = { registry = "https://pypi.org/simple" }
dependencies = [
    { name = "typing-extensions" },
]
sdist = { url = "https://files.pythonhosted.org/packages/x.tar.gz", hash = "sha256:abc", size = 1 }

[[package]]
name = "forked"
version = "0.1.0"
source = { git = "https://github.com/x/forked?rev=abc#abc" }
'''


def test_dependencies_match_tomllib():
    expected = tomllib.loads(PYPROJECT)["project"]["dependencies"]
    assert dependencies(PYPROJECT) == expected
    assert expected[1] == "click[extra]>=8"
    assert requires_python(PYPROJECT) == tomllib.loads(PYPROJECT)["project"]["requires-python"]


def test_table_span_stops_at_the_next_table():
    start, end = table_span(PYPROJECT, "project")
    assert 'name = "invoicer"' in PYPROJECT[start:end]
    assert "sphinx" not in PYPROJECT[start:end]
    assert table_span(PYPROJECT, "nothing") is None


def test_blank_dependencies_keeps_everything_else():
    blanked = blank_dependencies(PYPROJECT)
    assert "dependencies = []" in blanked
    assert "pydantic" not in blanked and 'testpaths = ["tests"]' in blanked
    upgraded = PYPROJECT.replace('"pydantic>=1.10.13,<2",  # the old major', '"pydantic==2.14.1",')
    assert blank_dependencies(upgraded) == blanked
    assert blank_dependencies(PYPROJECT.replace('requires-python = ">=3.12"', 'requires-python = ">=3.13"')) != blanked
    assert blank_dependencies("[tool.x]\ny = 1\n") == "[tool.x]\ny = 1\n"


def test_string_array_parsing_errors():
    assert parse_string_array(' "a", \'b\' , # c\n "d" ') == ["a", "b", "d"]
    assert parse_string_array("") == []
    for bad in ('"a" "b"', ', "a"', '"a', "x"):
        with pytest.raises(ValueError):
            parse_string_array(bad)
    with pytest.raises(ValueError):
        dependencies("[project]\nname = 'x'\n")


def test_lock_packages():
    packages = lock_packages(LOCK)
    assert [(package["name"], package["version"]) for package in packages] == [("invoicer", "1.4.0"), ("pydantic", "1.10.13"), ("forked", "0.1.0")]
    assert is_project(packages[0]["source"]) and not is_pypi(packages[0]["source"])
    assert is_pypi(packages[1]["source"]) and not is_project(packages[1]["source"])
    assert packages[2]["source"] == {"git": "https://github.com/x/forked?rev=abc#abc"}
    assert not is_pypi(packages[2]["source"]) and not is_project(packages[2]["source"])
    assert lock_packages("version = 1\n") == []
