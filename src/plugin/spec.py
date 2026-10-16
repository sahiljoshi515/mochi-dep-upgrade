"""The project's dependency spec, read the way the verifier reads it (``verifier.specs``) and checked
against a real parser of its kind, so a spec the two read differently is refused rather than judged
one way and verified another."""

from __future__ import annotations

import ast
import configparser
import tomllib

from plugin.common import ToolError
from verifier.specs import read_spec
from verifier.versions import parse_requirement


def _real(kind: str, text: str) -> list[str]:
    if kind == "pep621":
        return list(tomllib.loads(text)["project"]["dependencies"])
    if kind == "setup_cfg":
        parser = configparser.ConfigParser(interpolation=None)
        parser.read_string(text)
        value = parser["options"]["install_requires"]
        return [line.strip() for line in value.splitlines() if line.strip() and not line.strip().startswith(("#", ";"))]
    if kind == "setup_py":
        found = []
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.keyword) and node.arg == "install_requires":
                if isinstance(node.value, ast.Name):
                    continue
                if not isinstance(node.value, ast.List) or not all(isinstance(item, ast.Constant) and isinstance(item.value, str) for item in node.value.elts):
                    raise ValueError("install_requires is not a literal list of strings")
                found.append([item.value for item in node.value.elts])
        if not found:
            for node in ast.parse(text).body:
                if isinstance(node, ast.Assign) and any(isinstance(name, ast.Name) and name.id == "INSTALL_REQUIRES" for name in node.targets):
                    if not isinstance(node.value, ast.List) or not all(isinstance(item, ast.Constant) and isinstance(item.value, str) for item in node.value.elts):
                        raise ValueError("INSTALL_REQUIRES is not a literal list of strings")
                    found.append([item.value for item in node.value.elts])
        if len(found) != 1:
            raise ValueError(f"setup.py states install_requires {len(found)} times")
        return found[0]
    return read_spec(kind, text)[0]


def read(kind: str, text: str, *, name: str) -> tuple[list[str], str]:
    """``(requirements, text with them blanked)`` of the spec ``name``; raises ToolError when it is
    unreadable, when a requirement is not one this plugin accepts, or when a real parser of its
    kind reads it differently."""
    try:
        requirements, blanked = read_spec(kind, text)
    except ValueError as error:
        raise ToolError(f"{name} cannot be read: {error}") from error
    try:
        real = _real(kind, text)
    except (ValueError, SyntaxError, KeyError, tomllib.TOMLDecodeError, configparser.Error) as error:
        raise ToolError(f"{name} is not valid: {error}") from error
    if [item.strip() for item in real] != [item.strip() for item in requirements]:
        raise ToolError(f"{name} reads differently with a {kind} parser; write its requirements as a plain list of strings")
    for item in requirements:
        try:
            parse_requirement(item)
        except ValueError as error:
            raise ToolError(f"{name}: {error}") from error
    return requirements, blanked
