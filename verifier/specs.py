"""Reading a project's dependency spec, the one file that declares its runtime requirements, without
a TOML or Python parser: ``pyproject.toml``'s ``[project] dependencies`` (pep621), ``setup.cfg``'s
``[options] install_requires`` (setup_cfg), ``setup.py``'s literal ``install_requires=[...]``
(setup_py), or a requirements file (requirements_txt).

``read_spec(kind, text)`` returns the requirements as written and the file's text with that region
blanked: an upgrade may change the region, and nothing else in the file. The tools and the verifier
call the same functions, so the record and the verdict read a spec the same way.
"""

import re

KINDS = ("pep621", "setup_cfg", "setup_py", "requirements_txt")

TABLE_HEADER = re.compile(r"^\s*\[\[?\s*([^\]]*?)\s*\]\]?\s*(?:#.*)?$", re.MULTILINE)
DEPENDENCIES_KEY = re.compile(r"^[ \t]*dependencies[ \t]*=[ \t]*\[", re.MULTILINE)
INSTALL_REQUIRES_PY = re.compile(r"\binstall_requires\s*=\s*\[")
INSTALL_REQUIRES_VARIABLE = re.compile(r"^INSTALL_REQUIRES\s*=\s*\[", re.MULTILINE)
CFG_SECTION = re.compile(r"^\[([^\]\n]+)\][ \t]*$", re.MULTILINE)
CFG_INSTALL_REQUIRES = re.compile(r"^install_requires[ \t]*[=:][ \t]*(.*)$", re.MULTILINE)


def table_span(text, name):
    """The ``(start, end)`` of the body of the TOML table ``[name]`` in ``text``, or None."""
    start = None
    for found in TABLE_HEADER.finditer(text):
        if start is not None:
            return start, found.start()
        if found.group(1) == name and not found.group(0).lstrip().startswith("[["):
            start = found.end()
    return None if start is None else (start, len(text))


def scan_array(text, opening):
    """Given the index of a ``[`` in ``text``, the index of its matching ``]``, skipping quoted
    strings and ``#`` comments; None when it never closes."""
    index = opening + 1
    depth = 1
    size = len(text)
    while index < size:
        char = text[index]
        if char in "\"'":
            quote = char
            index += 1
            while index < size and text[index] != quote:
                if text[index] == "\\":
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


def parse_string_array(inner):
    """The strings of an array body (between its brackets) of quoted strings, commas, whitespace and
    ``#`` comments, as TOML and Python both write it; raises ValueError on anything else (an
    expression, a name, implicit concatenation)."""
    items = []
    index = 0
    size = len(inner)
    expect_item = True
    escapes = {"n": "\n", "t": "\t", '"': '"', "'": "'", "\\": "\\", "r": "\r"}
    while index < size:
        char = inner[index]
        if char in " \t\r\n":
            index += 1
        elif char == "#":
            while index < size and inner[index] != "\n":
                index += 1
        elif char == ",":
            if expect_item:
                raise ValueError("unexpected comma in the requirements list")
            expect_item = True
            index += 1
        elif char in "\"'":
            if not expect_item:
                raise ValueError("missing comma in the requirements list")
            quote = char
            index += 1
            start = index
            value = []
            while index < size and inner[index] != quote:
                if inner[index] == "\n":
                    raise ValueError(f"a requirement string runs past its line at {start}")
                if inner[index] == "\\":
                    index += 1
                    if index >= size:
                        break
                    value.append(escapes.get(inner[index], inner[index]))
                else:
                    value.append(inner[index])
                index += 1
            if index >= size:
                raise ValueError(f"unterminated string in the requirements list at {start}")
            items.append("".join(value))
            index += 1
            expect_item = False
        else:
            raise ValueError(f"the requirements list holds something that is not a string: {inner[index:index + 20]!r}")
    return items


def _pep621(text):
    span = table_span(text, "project")
    if span is None:
        raise ValueError("pyproject.toml has no [project] table")
    found = DEPENDENCIES_KEY.search(text, span[0], span[1])
    if not found:
        raise ValueError("pyproject.toml has no [project] dependencies array")
    opening = found.end() - 1
    closing = scan_array(text, opening)
    if closing is None:
        raise ValueError("the [project] dependencies array never closes")
    return parse_string_array(text[opening + 1 : closing]), text[: opening + 1] + text[closing:]


def _setup_py(text):
    found = list(INSTALL_REQUIRES_PY.finditer(text))
    if not found:
        # The other common form: a module-level INSTALL_REQUIRES = [...] passed to setup().
        found = list(INSTALL_REQUIRES_VARIABLE.finditer(text))
    if len(found) != 1:
        raise ValueError(f"setup.py must state install_requires=[...] (or INSTALL_REQUIRES = [...]) exactly once as a literal list (found {len(found)})")
    opening = found[0].end() - 1
    closing = scan_array(text, opening)
    if closing is None:
        raise ValueError("setup.py's install_requires list never closes")
    return parse_string_array(text[opening + 1 : closing]), text[: opening + 1] + text[closing:]


def _setup_cfg(text):
    sections = list(CFG_SECTION.finditer(text))
    options = [found for found in sections if found.group(1).strip() == "options"]
    if len(options) != 1:
        raise ValueError("setup.cfg must have exactly one [options] section")
    start = options[0].end()
    following = [found.start() for found in sections if found.start() > start]
    end = following[0] if following else len(text)
    keys = list(CFG_INSTALL_REQUIRES.finditer(text, start, end))
    if len(keys) != 1:
        raise ValueError("setup.cfg's [options] must state install_requires exactly once")
    key = keys[0]
    value_start = key.start(1)
    lines = [key.group(1)] if key.group(1).strip() else []
    value_end = key.end()
    # Continuation lines are indented; blank lines between them belong to the value too.
    position = key.end()
    while position < end and text[position] == "\n":
        line_start = position + 1
        newline = text.find("\n", line_start, end)
        line_end = end if newline < 0 else newline
        line = text[line_start:line_end]
        if line.strip() and line[:1] not in (" ", "\t"):
            break
        if line.strip():
            lines.append(line)
            value_end = line_end
        position = line_end
    requirements = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        requirements.append(stripped)
    return requirements, text[:value_start] + text[value_end:]


def _requirements_txt(text):
    requirements = []
    for line in text.splitlines():
        stripped = line.split(" #", 1)[0].strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("-"):
            raise ValueError(f"a requirements file option is not supported here: {stripped[:40]!r}")
        requirements.append(stripped)
    return requirements, ""


READERS = {"pep621": _pep621, "setup_cfg": _setup_cfg, "setup_py": _setup_py, "requirements_txt": _requirements_txt}


def read_spec(kind, text):
    """``(requirements as written, text with the requirements region blanked)``; raises ValueError
    when the spec cannot be read the way ``kind`` says."""
    if kind not in READERS:
        raise ValueError(f"unknown spec kind {kind!r}")
    return READERS[kind](text)


def requires_python(text):
    """pyproject.toml's ``[project] requires-python`` string, or empty."""
    span = table_span(text, "project")
    if span is None:
        return ""
    found = re.compile(r"""^[ \t]*requires-python[ \t]*=[ \t]*(?:"([^"\n]*)"|'([^'\n]*)')""", re.MULTILINE).search(text, span[0], span[1])
    if not found:
        return ""
    return found.group(1) if found.group(1) is not None else found.group(2)
