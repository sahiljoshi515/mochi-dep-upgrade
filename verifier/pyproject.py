"""Regex readers for ``pyproject.toml``'s ``[project]`` table and for ``uv.lock``: enough for the
checks here, without a TOML parser. The tools read the pristine files with the same functions, so
the pin and the verdict see the same thing."""

import re

TABLE_HEADER = re.compile(r"^\s*\[\[?\s*([^\]]*?)\s*\]\]?\s*(?:#.*)?$", re.MULTILINE)
DEPENDENCIES_KEY = re.compile(r"^[ \t]*dependencies[ \t]*=[ \t]*\[", re.MULTILINE)
REQUIRES_PYTHON = re.compile(r"""^[ \t]*requires-python[ \t]*=[ \t]*(?:"([^"\n]*)"|'([^'\n]*)')""", re.MULTILINE)
PACKAGE_HEADER = re.compile(r"^\[\[package\]\][ \t]*$", re.MULTILINE)
LOCK_NAME = re.compile(r'^name = "([^"\n]*)"', re.MULTILINE)
LOCK_VERSION = re.compile(r'^version = "([^"\n]*)"', re.MULTILINE)
LOCK_SOURCE = re.compile(r"^source = \{(.*)\}[ \t]*$", re.MULTILINE)
SOURCE_ITEM = re.compile(r"""([A-Za-z0-9_-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^,}\s]+))""")
PYPI_REGISTRY = "https://pypi.org/simple"


def table_span(text, name):
    """The ``(start, end)`` of the body of the table ``[name]`` in ``text``, or None."""
    start = None
    for found in TABLE_HEADER.finditer(text):
        if start is not None:
            return start, found.start()
        if found.group(1) == name and not found.group(0).lstrip().startswith("[["):
            start = found.end()
    return None if start is None else (start, len(text))


def scan_array(text, opening):
    """Given the index of a ``[`` in ``text``, the index of its matching ``]``, skipping quoted
    strings and comments; None when it never closes."""
    index = opening + 1
    depth = 1
    size = len(text)
    while index < size:
        char = text[index]
        if char in "\"'":
            quote = char
            index += 1
            while index < size and text[index] != quote:
                if text[index] == "\\" and quote == '"':
                    index += 1
                index += 1
        elif char == "#":
            while index < size and text[index] != "\n":
                index += 1
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def dependencies_span(text):
    """``(open, close)`` indexes of the ``[`` and ``]`` of ``[project]``'s ``dependencies`` array,
    or None when the table or the key is missing."""
    span = table_span(text, "project")
    if span is None:
        return None
    found = DEPENDENCIES_KEY.search(text, span[0], span[1])
    if not found:
        return None
    opening = found.end() - 1
    closing = scan_array(text, opening)
    if closing is None:
        return None
    return opening, closing


def parse_string_array(inner):
    """The strings of a TOML array body (between its brackets); raises ValueError on anything
    else than quoted strings, commas, whitespace and comments."""
    items = []
    index = 0
    size = len(inner)
    expect_item = True
    while index < size:
        char = inner[index]
        if char in " \t\r\n":
            index += 1
        elif char == "#":
            while index < size and inner[index] != "\n":
                index += 1
        elif char == ",":
            if expect_item:
                raise ValueError("unexpected comma in the dependencies array")
            expect_item = True
            index += 1
        elif char in "\"'":
            if not expect_item:
                raise ValueError("missing comma in the dependencies array")
            quote = char
            index += 1
            start = index
            value = []
            while index < size and inner[index] != quote:
                if inner[index] == "\\" and quote == '"':
                    index += 1
                    if index >= size:
                        break
                    escapes = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "r": "\r"}
                    value.append(escapes.get(inner[index], inner[index]))
                else:
                    value.append(inner[index])
                index += 1
            if index >= size:
                raise ValueError(f"unterminated string in the dependencies array at {start}")
            items.append("".join(value))
            index += 1
            expect_item = False
        else:
            raise ValueError(f"the dependencies array holds something that is not a string: {inner[index:index + 20]!r}")
    return items


def dependencies(text):
    """The ``[project]`` ``dependencies`` strings, as written; raises ValueError when unreadable."""
    span = dependencies_span(text)
    if span is None:
        raise ValueError("pyproject.toml has no [project] dependencies array")
    return parse_string_array(text[span[0] + 1 : span[1]])


def blank_dependencies(text):
    """``text`` with the ``[project]`` ``dependencies`` array emptied: what must stay the same."""
    span = dependencies_span(text)
    if span is None:
        return text
    return text[: span[0] + 1] + text[span[1] :]


def requires_python(text):
    """The ``[project]`` ``requires-python`` string, or empty."""
    span = table_span(text, "project")
    if span is None:
        return ""
    found = REQUIRES_PYTHON.search(text, span[0], span[1])
    if not found:
        return ""
    return found.group(1) if found.group(1) is not None else found.group(2)


def lock_packages(text):
    """Every ``[[package]]`` of a ``uv.lock``: ``{"name", "version", "source": {key: value}}``."""
    headers = list(PACKAGE_HEADER.finditer(text))
    packages = []
    for number, header in enumerate(headers):
        end = headers[number + 1].start() if number + 1 < len(headers) else len(text)
        block = text[header.end() : end]
        name = LOCK_NAME.search(block)
        version = LOCK_VERSION.search(block)
        source_line = LOCK_SOURCE.search(block)
        source = {}
        if source_line:
            for item in SOURCE_ITEM.finditer(source_line.group(1)):
                source[item.group(1)] = next(value for value in item.groups()[1:] if value is not None)
        packages.append(
            {
                "name": name.group(1) if name else "",
                "version": version.group(1) if version else "",
                "source": source,
            }
        )
    return packages


def is_pypi(source):
    return source.get("registry") == PYPI_REGISTRY


def is_project(source):
    return "editable" in source or "virtual" in source
