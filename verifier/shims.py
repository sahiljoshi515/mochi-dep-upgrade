"""Finding shims in what the upgrade added, read from the code's tokens (the verifier may not import
``ast``; the judge also reads the code with ``ast``, in ``plugin.shims``, and records what it finds).

Each changed editable ``.py`` file is tokenized. Names resolve through the file's imports and simple
aliases (``import warnings as w``, ``f = getattr(w, "simplefilter")``), strings fold (adjacent literals,
``+``, ``"".join([...])``, ``chr(...)``, ``.lower()``, reversing slices, escapes, rot13), and
``getattr``, ``vars``, ``__dict__``, ``sys.modules[...]``, ``import_module`` and ``__import__`` are
followed when their names fold. Every statement on an added line is then checked against these rules:

- ``warnings``: what silences or reroutes warnings, however it is reached: the filter API
  (``filterwarnings``, ``simplefilter``, ``resetwarnings``, ``catch_warnings``), the filter list and
  registries, ``logging.captureWarnings``, ``PYTHONWARNINGS``, and assigning (or ``setattr``-ing) any
  attribute of the warnings module (``showwarning``, ``formatwarning``, ...). Emitting a warning
  (``warnings.warn``, ``warn_explicit``, a deprecation notice) is not a shim.
- ``import-system``: ``sys.modules``, ``sys.path``, ``sys.meta_path`` and import hooks, reloading,
  ``__import__``, ``import_module`` of a computed or guarded name.
- ``reflection``: ``getattr``, ``setattr``, ``delattr``, ``vars`` or ``__dict__`` on a module;
  ``globals()``, ``builtins``, ``__builtins__``.
- ``dynamic-code``: ``exec``, ``eval``, ``compile``.
- ``patches-dependency``: assigning, deleting or ``setattr``-ing an attribute of the dependency's
  modules or objects; ``mock``.
- ``version-sniff``: the dependency's ``__version__``, ``VERSION`` or ``version_info``, an
  ``importlib.metadata`` lookup of it (or of a computed name), ``pkg_resources``.
- ``test-sniff``: pytest, ``sys.argv``, ``PYTEST_*`` names, ``sys._getframe``.
- ``old-api``: the copy of its old API the library still ships (``old_api`` in the catalog, as
  ``pydantic.v1``) instead of the new one.

An instance exempts a rule only when upstream's own change needs it (``shim_exempt``). Reading code
cannot catch everything; the judge's import probe (``plugin.probe``) shows what importing the project
does. The judge and the verifier both call :func:`scan`.
"""

import difflib
import itertools
import json
import re
from pathlib import Path

from .trees import text_lines
from .versions import canonical_name

MAX_FOUND = 30
RULES = ("warnings", "import-system", "reflection", "dynamic-code", "patches-dependency", "version-sniff", "test-sniff", "old-api", "unreadable")
# Copies of their old API that libraries ship alongside the new one: using them is not migrating.
OLD_API = {"pydantic": ["pydantic.v1"]}
# Names that silence or reroute warnings, wherever they appear in a resolved name or a string.
SILENCING = frozenset({"filterwarnings", "simplefilter", "resetwarnings", "catch_warnings", "suppress_warnings", "captureWarnings", "PYTHONWARNINGS", "__warningregistry__", "_filters_mutated", "_filters_mutated_lock_held", "_add_filter", "_processoptions", "_setoption", "warnoptions"})
# The warnings module's own state: reaching it at all is the first step to changing it.
WARNING_STATE = frozenset({"filters", "onceregistry", "_onceregistry", "_filters_version"})
# The warnings module itself (assigning any of its attributes reroutes warnings).
WARNING_MODULES = frozenset({"warnings", "_warnings"})
# Attribute names of the filter API: flagged on any object, even one whose name does not resolve.
WARNING_ATTRS = frozenset({"filterwarnings", "simplefilter", "resetwarnings", "catch_warnings", "suppress_warnings", "captureWarnings", "__warningregistry__", "_filters_mutated"})
IMPORT_SYSTEM = ("sys.modules", "sys.path", "sys.meta_path", "sys.path_hooks", "sys.path_importer_cache", "importlib.reload", "importlib.invalidate_caches", "importlib.util", "importlib.machinery", "importlib.abc", "imp", "builtins.__import__", "<builtin>.__import__", "<builtin>.reload")
TEST_SNIFF = ("sys.argv", "sys.orig_argv", "sys._getframe", "pytest", "_pytest")
DYNAMIC_CODE = frozenset({"<builtin>.exec", "<builtin>.eval", "<builtin>.compile", "builtins.exec", "builtins.eval", "builtins.compile"})
VERSION_PARTS = frozenset({"__version__", "VERSION", "version_info", "__version_info__", "version", "_version", "__about__", "__version_tuple__", "version_tuple"})
METADATA = ("importlib.metadata", "importlib_metadata")
METADATA_CALLS = frozenset({"version", "distribution", "metadata", "files", "requires", "from_name", "packages_distributions"})
GUARDED_MODULES = frozenset({"warnings", "_warnings", "sys", "builtins", "importlib", "imp"})
REFLECTORS = frozenset({"getattr", "setattr", "delattr", "hasattr", "vars"})
IMPORTERS = frozenset({"<builtin>.__import__", "builtins.__import__", "importlib.import_module", "importlib.__import__"})
# The builtins a name can stand for here (any other name that does not resolve is unknown).
BUILTINS = frozenset({"getattr", "setattr", "delattr", "hasattr", "vars", "globals", "locals", "exec", "eval", "compile", "__import__", "__builtins__", "chr", "str", "reload", "object", "type"})
CASE_METHODS = frozenset({"lower", "upper", "strip", "lstrip", "rstrip", "title", "casefold", "capitalize", "swapcase"})
IDENTIFIER_PATH = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
LINE_BREAK = re.compile(r"\r\n|\r|\n")
TOKEN = re.compile(
    r"""
    (?P<comment>\#[^\r\n]*)
  | (?P<string>(?:[rRbBuUfF]|[rR][bBfF]|[bBfF][rR])?(?:'''(?:[^'\\]|\\[\s\S]|'(?!''))*'''|\"\"\"(?:[^"\\]|\\[\s\S]|"(?!""))*\"\"\"|'(?:[^'\\\r\n]|\\[\s\S])*'|"(?:[^"\\\r\n]|\\[\s\S])*"))
  | (?P<name>[^\W\d]\w*)
  | (?P<number>\d[\w.]*)
  | (?P<continuation>\\(?:\r\n|\r|\n))
  | (?P<newline>\r\n|\r|\n)
  | (?P<space>[ \t\f]+)
  | (?P<op>\*\*=?|//=?|->|:=|==|!=|<=|>=|<<=?|>>=?|[-+*/%&|^@]=|[()\[\]{}.,:;=<>+\-*/%&|^~@!])
  | (?P<other>.)
    """,
    re.VERBOSE,
)
ESCAPE = re.compile(r"\\(x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}|[0-7]{1,3}|[\s\S])")
# In an f-string: an escaped brace, a field that is one string literal, or any other brace.
FIELD = re.compile(r"""\{\{|\}\}|\{\s*('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")\s*\}|[{}]""")
SIMPLE_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "\\": "\\", "'": "'", '"': '"', "a": "\a", "b": "\b", "f": "\f", "v": "\v"}
OPENING, CLOSING = frozenset("([{"), frozenset(")]}")


def python_lines(data):
    """Bytes as lines numbered the way Python numbers them (only \\n, \\r\\n and \\r end a line)."""
    lines = LINE_BREAK.split(data.decode("utf-8", errors="replace"))
    return lines[:-1] if lines and lines[-1] == "" else lines


def added_with_numbers(before, after):
    """``(line number in after, text)`` of every line of ``after`` new against ``before``."""
    found = []
    for tag, _, _, start, end in difflib.SequenceMatcher(None, before, after, autojunk=False).get_opcodes():
        if tag in ("replace", "insert"):
            found.extend((index + 1, after[index]) for index in range(start, end))
    return found


def pristine_bytes(root, item):
    if item["status"] == "added":
        return b""
    pristine = Path(root) / ".judge" / "pristine" / item["path"]
    return pristine.read_bytes() if pristine.is_file() else b""


def added_lines_by_file(root, changed):
    """path -> ``[(line number, text)]`` added, for every added or modified file in ``changed``
    (``[{"path", "status"}]``), against the pristine copies under ``root/.judge/pristine``."""
    root = Path(root)
    out = {}
    for item in changed:
        if item["status"] == "deleted":
            continue
        out[item["path"]] = added_with_numbers(text_lines(pristine_bytes(root, item)), text_lines((root / item["path"]).read_bytes()))
    return out


def starts(path, prefix):
    return path == prefix or path.startswith(prefix + ".")


def is_warnings_module(path):
    """Whether ``path`` names the warnings module (``warnings``, ``_warnings``, ``logging.warnings``)."""
    return bool(path) and path.split(".")[-1] in WARNING_MODULES


def path_rule(path, dependency, old_api):
    """The rule a resolved name alone breaks, or None."""
    if not path:
        return None
    parts = path.split(".")
    if any(part in SILENCING for part in parts) or any(part in WARNING_MODULES and following in WARNING_STATE for part, following in itertools.pairwise(parts)):
        return "warnings"
    if any(starts(path, prefix) for prefix in IMPORT_SYSTEM):
        return "import-system"
    if any(starts(path, prefix) for prefix in TEST_SNIFF):
        return "test-sniff"
    if path in DYNAMIC_CODE:
        return "dynamic-code"
    if starts(path, "builtins") or path in ("<builtin>.globals", "<builtin>.__builtins__"):
        return "reflection"
    if any(starts(path, prefix) for prefix in old_api):
        return "old-api"
    if starts(path, "pkg_resources") or (any(starts(path, name) for name in dependency) and any(part in VERSION_PARTS for part in parts[1:])):
        return "version-sniff"
    if starts(path, "mock") or starts(path, "unittest.mock"):
        return "patches-dependency"
    return None


def string_rule(text):
    """The rule a string names, when it is a dotted name: ``"warnings"``, ``"PYTEST_CURRENT_TEST"``."""
    text = text.strip()
    if not IDENTIFIER_PATH.fullmatch(text):
        return None
    parts = text.split(".")
    if any(part in SILENCING for part in parts):
        return "warnings"
    if text.startswith("PYTEST") or parts[0] in ("pytest", "_pytest"):
        return "test-sniff"
    if text in ("sys.modules", "__import__"):
        return "import-system"
    if text == "__builtins__":
        return "reflection"
    return None


def rot13(text):
    out = []
    for char in text:
        if "a" <= char <= "z":
            char = chr((ord(char) - 97 + 13) % 26 + 97)
        elif "A" <= char <= "Z":
            char = chr((ord(char) - 65 + 13) % 26 + 65)
        out.append(char)
    return "".join(out)


def unescape(text):
    """A non-raw literal's backslash escapes, decoded."""

    def one(found):
        code = found.group(1)
        if code[0] in "xuU":
            return chr(int(code[1:], 16))
        if code[0] in "01234567":
            return chr(int(code, 8))
        return SIMPLE_ESCAPES.get(code, "\\" + code)

    return ESCAPE.sub(one, text)


def literal(text):
    """The value of one string token, or None: a bytes literal, or an f-string with a field that is not
    a plain string literal (no conversion, no format spec), has no string value here."""
    match = re.match(r"([rRbBuUfF]*)('''|\"\"\"|'|\")", text)
    prefix, quote = match.group(1).lower(), match.group(2)
    body = text[len(match.group(1)) + len(quote) : len(text) - len(quote)]
    if "b" in prefix:
        return None
    plain = (lambda piece: piece) if "r" in prefix else unescape
    if "f" not in prefix:
        return plain(body)
    out, last = [], 0
    for found in FIELD.finditer(body):
        out.append(plain(body[last : found.start()]))
        piece = found.group()
        if piece in ("{{", "}}"):
            out.append(piece[0])
        elif found.group(1):
            value = literal(found.group(1))
            if value is None:
                return None
            out.append(value)
        else:
            return None
        last = found.end()
    out.append(plain(body[last:]))
    return "".join(out)


class Token:
    def __init__(self, kind, text, line, last):
        self.kind, self.text, self.line, self.last = kind, text, line, last


def tokenize(text):
    """The code's tokens, without spaces, comments and line continuations; newlines kept."""
    tokens = []
    line = 1
    for found in TOKEN.finditer(text):
        kind, value = found.lastgroup, found.group()
        breaks = len(LINE_BREAK.findall(value))
        if kind not in ("space", "comment", "continuation"):
            tokens.append(Token(kind, value, line, line + breaks))
        line += breaks
    return tokens


def statements(tokens):
    """Logical lines: token lists split at newlines and semicolons outside brackets."""
    out, current, depth = [], [], 0
    for token in tokens:
        if token.kind == "op" and token.text in OPENING:
            depth += 1
        elif token.kind == "op" and token.text in CLOSING:
            depth = max(0, depth - 1)
        if depth == 0 and (token.kind == "newline" or (token.kind == "op" and token.text == ";")):
            if current:
                out.append(current)
            current = []
            continue
        if token.kind != "newline":
            current.append(token)
    if current:
        out.append(current)
    return out


def closing(tokens, start):
    """The index of the bracket closing the one at ``start``."""
    depth = 0
    for index in range(start, len(tokens)):
        if tokens[index].kind == "op" and tokens[index].text in OPENING:
            depth += 1
        elif tokens[index].kind == "op" and tokens[index].text in CLOSING:
            depth -= 1
            if depth == 0:
                return index
    return len(tokens) - 1


def split_top(tokens, separator):
    """``tokens`` split at ``separator`` outside brackets."""
    parts, current, depth = [], [], 0
    for token in tokens:
        if token.kind == "op" and token.text in OPENING:
            depth += 1
        elif token.kind == "op" and token.text in CLOSING:
            depth -= 1
        if depth == 0 and token.kind == "op" and token.text == separator:
            parts.append(current)
            current = []
        else:
            current.append(token)
    parts.append(current)
    return parts


class Reader:
    """What the names of one module refer to, read from its import statements and simple aliases, and
    what its string expressions always evaluate to."""

    def __init__(self, logical):
        self.bound = {}
        self.modules = set()
        self.defined = set()
        for tokens in logical:
            texts = [token.text for token in tokens]
            if texts and texts[0] == "import":
                for part in split_top(tokens[1:], ","):
                    words = [token.text for token in part]
                    if "as" in words:
                        name = words[words.index("as") + 1]
                        self.bound[name] = "".join(words[: words.index("as")])
                    elif words:
                        name = words[0]
                        self.bound[name] = name
                    else:
                        continue
                    self.modules.add(name)
            elif texts and texts[0] == "from" and "import" in texts:
                base = "".join(texts[1 : texts.index("import")])
                for part in split_top([token for token in tokens[texts.index("import") + 1 :] if token.text not in ("(", ")")], ","):
                    words = [token.text for token in part]
                    if not words or words[0] == "*":
                        continue
                    name = words[words.index("as") + 1] if "as" in words else words[0]
                    self.bound[name] = f"{base}.{words[0]}" if base and not base.endswith(".") else base + words[0]
            elif len(texts) > 1 and texts[0] in ("def", "class"):
                self.defined.add(texts[1])
            elif len(texts) > 2 and tokens[0].kind == "name" and texts[1] == "=":
                self.defined.add(texts[0])
        for _ in range(3):  # simple aliases, a few levels deep: x = warnings; f = getattr(x, "simplefilter")
            for tokens in logical:
                if len(tokens) > 2 and tokens[0].kind == "name" and tokens[1].text == "=" and tokens[0].text not in self.modules:
                    path, end = self.resolve(tokens, 2)
                    if path and end == len(tokens):
                        self.bound[tokens[0].text] = path

    def is_module(self, tokens):
        """Whether the expression ``tokens`` is a module object: a name bound by import, a guarded
        module, or what an import function or ``sys.modules[...]`` returns."""
        if len(tokens) == 1 and tokens[0].text in self.modules:
            return True
        path, end = self.resolve(tokens, 0)
        if end != len(tokens):
            return False
        if path in GUARDED_MODULES or path == "builtins":
            return True
        if tokens[-1].text in (")", "]"):
            opening = next((position for position in range(len(tokens)) if tokens[position].text in ("(", "[") and closing(tokens, position) == len(tokens) - 1), None)
            if opening:
                before, after = self.resolve(tokens[:opening], 0)
                if after == opening:
                    return (tokens[opening].text == "(" and before in IMPORTERS) or (tokens[opening].text == "[" and before == "sys.modules")
        return False

    def name(self, text):
        if text in self.bound:
            return self.bound[text]
        if text in BUILTINS and text not in self.defined:
            return "<builtin>." + text
        return None

    def resolve(self, tokens, start, steps=None):
        """``(dotted name of the expression at start, index after it)``; each name reached on the way
        goes into ``steps`` when given."""
        if start >= len(tokens) or tokens[start].kind != "name":
            return None, start + 1
        path = self.name(tokens[start].text)
        if steps is not None and path:
            steps.append((path, tokens[start]))
        index = start + 1
        while index < len(tokens):
            token = tokens[index]
            if token.text == "." and index + 1 < len(tokens) and tokens[index + 1].kind == "name":
                path = f"{path}.{tokens[index + 1].text}" if path else None
                index += 2
            elif token.text == "(":
                end = closing(tokens, index)
                arguments = split_top(tokens[index + 1 : end], ",")
                path = self.call_result(path, arguments)
                index = end + 1
            elif token.text == "[":
                end = closing(tokens, index)
                key = self.fold(tokens[index + 1 : end])
                if path == "sys.modules" and key:
                    path = key
                elif path and path.endswith(".__dict__") and key:
                    path = f"{path[: -len('.__dict__')]}.{key}"
                else:
                    path = None
                index = end + 1
            else:
                break
            if steps is not None and path:
                steps.append((path, token))
        return path, index

    def call_result(self, path, arguments):
        if path in ("<builtin>.getattr", "builtins.getattr") and len(arguments) >= 2:
            base, end = self.resolve(arguments[0], 0)
            name = self.fold(arguments[1])
            return f"{base}.{name}" if base and end == len(arguments[0]) and name else None
        if path in IMPORTERS and arguments and arguments[0]:
            return self.fold(arguments[0])
        if path in ("<builtin>.vars", "builtins.vars") and arguments and arguments[0]:
            base, end = self.resolve(arguments[0], 0)
            return f"{base}.__dict__" if base and end == len(arguments[0]) else None
        return None

    def fold(self, tokens):
        """The string ``tokens`` always evaluate to, or None."""
        while len(tokens) > 2 and tokens[0].text == "(" and closing(tokens, 0) == len(tokens) - 1:
            tokens = tokens[1:-1]
        if not tokens:
            return None
        parts = split_top(tokens, "+")
        if len(parts) > 1:
            values = [self.fold(part) for part in parts]
            return "".join(values) if all(value is not None for value in values) else None
        return self.fold_term(tokens)

    def fold_term(self, tokens):
        index, value = 0, None
        if tokens[0].kind == "string":
            pieces = []
            while index < len(tokens) and tokens[index].kind == "string":
                pieces.append(literal(tokens[index].text))
                index += 1
            value = "".join(pieces) if all(piece is not None for piece in pieces) else None
        elif tokens[0].kind == "name" and len(tokens) > 3 and tokens[1].text == "(":
            end = closing(tokens, 1)
            arguments = split_top(tokens[2:end], ",")
            function = self.name(tokens[0].text)
            if function == "<builtin>.chr" and len(arguments) == 1 and len(arguments[0]) == 1 and arguments[0][0].kind == "number" and arguments[0][0].text.isdigit():
                value = chr(min(int(arguments[0][0].text), 0x10FFFF))
            elif function == "<builtin>.str" and len(arguments) == 1:
                value = self.fold(arguments[0])
            index = end + 1
        elif tokens[0].kind == "name":
            opening = next((position for position, token in enumerate(tokens) if token.text == "("), None)
            if opening is None or closing(tokens, opening) != len(tokens) - 1:
                return None
            callee, end = self.resolve(tokens[:opening], 0)
            arguments = split_top(tokens[opening + 1 : -1], ",")
            if callee in ("codecs.decode", "codecs.encode") and end == opening and len(arguments) == 2:
                text, codec = self.fold(arguments[0]), self.fold(arguments[1])
                if text is not None and codec and codec.replace("_", "").lower() == "rot13":
                    return rot13(text)
            return None
        elif tokens[0].text == "(":
            end = closing(tokens, 0)
            value, index = self.fold(tokens[1:end]), end + 1
        while value is not None and index < len(tokens):
            token = tokens[index]
            if token.text == "." and index + 2 < len(tokens) and tokens[index + 2].text == "(":
                method, end = tokens[index + 1].text, closing(tokens, index + 2)
                arguments = [part for part in split_top(tokens[index + 3 : end], ",") if part]
                if method == "join" and len(arguments) == 1 and arguments[0][0].text in "([" and closing(arguments[0], 0) == len(arguments[0]) - 1:
                    items = [self.fold(item) for item in split_top(arguments[0][1:-1], ",") if item]
                    value = value.join(items) if all(item is not None for item in items) else None
                elif method in CASE_METHODS and not arguments:
                    value = {"lower": value.lower, "upper": value.upper, "strip": value.strip, "lstrip": value.lstrip, "rstrip": value.rstrip, "title": value.title, "casefold": value.casefold, "capitalize": value.capitalize, "swapcase": value.swapcase}[method]()
                elif method == "replace" and len(arguments) == 2:
                    old, new = self.fold(arguments[0]), self.fold(arguments[1])
                    value = value.replace(old, new) if old is not None and new is not None else None
                else:
                    value = None
                index = end + 1
            elif token.text == "[":
                end = closing(tokens, index)
                value, index = slice_of(value, tokens[index + 1 : end]), end + 1
            else:
                return None
        return value


def slice_of(value, tokens):
    """``value[a:b:c]`` for literal integers, or None."""
    bounds, current, numbers = [], [], 0
    for token in [*tokens, Token("op", ":", 0, 0)]:
        if token.text == ":":
            numbers += 1
            text = "".join(item.text for item in current)
            if text and not re.fullmatch(r"-?\d+", text):
                return None
            bounds.append(int(text) if text else None)
            current = []
        else:
            current.append(token)
    if not 2 <= numbers <= 3 or (len(bounds) == 3 and bounds[2] == 0):
        return None
    return value[slice(*bounds)]


def statement_problems(tokens, reader, added, dependency, old_api):
    """``(line, rule, detail)`` for one logical line touching an added line."""
    found = []

    def flag(rule, token, detail):
        found.append((token.line, rule, detail[:80]))

    def on_added(token):
        return any(line in added for line in range(token.line, token.last + 1))

    def is_dependency(path):
        return bool(path) and any(starts(path, name) for name in dependency)

    texts = [token.text for token in tokens]
    if texts[0] in ("import", "from") and any(on_added(token) for token in tokens):
        if texts[0] == "import":
            for part in split_top(tokens[1:], ","):
                words = [token.text for token in part]
                module = "".join(words[: words.index("as")] if "as" in words else words)
                rule = path_rule(module, dependency, old_api)
                if rule:
                    flag(rule, tokens[0], module)
        elif "import" in texts:
            base = "".join(texts[1 : texts.index("import")])
            if not base.startswith("."):
                rule = path_rule(base, dependency, old_api)
                names = [part[0].text for part in split_top([token for token in tokens[texts.index("import") + 1 :] if token.text not in ("(", ")")], ",") if part]
                for name in names:
                    if rule:
                        break
                    rule = path_rule(f"{base}.{name}", dependency, old_api)
                if rule:
                    flag(rule, tokens[0], base)
        return found
    # Names and what they reach.
    for index, token in enumerate(tokens):
        if token.kind != "name" or (index and tokens[index - 1].text == ".") or not on_added(token):
            continue
        steps = []
        reader.resolve(tokens, index, steps)
        for path, step in steps:
            rule = path_rule(path, dependency, old_api)
            if rule:
                flag(rule, token, path)
        head = reader.name(token.text)
        if index + 1 < len(tokens) and tokens[index + 1].text == "(":
            end = closing(tokens, index + 1)
            arguments = split_top(tokens[index + 2 : end], ",")
            kind = head.split(".")[-1] if head and head.startswith(("<builtin>.", "builtins.")) else ""
            if kind in REFLECTORS and arguments and arguments[0]:
                target, target_end = reader.resolve(arguments[0], 0)
                target = target if target_end == len(arguments[0]) else None
                name = reader.fold(arguments[1]) if len(arguments) > 1 else None
                if target and name:
                    rule = path_rule(f"{target}.{name}", dependency, old_api)
                    if rule:
                        flag(rule, token, f"{target}.{name}")
                if kind in ("setattr", "delattr") and is_dependency(target):
                    flag("patches-dependency", token, f"{kind}({target}, ...)")
                if kind in ("setattr", "delattr") and is_warnings_module(target):
                    flag("warnings", token, f"{kind}({target}, ...)")
                if kind != "hasattr" and reader.is_module(arguments[0]):
                    flag("reflection", token, f"{kind}() on the module {target}")
                elif kind in ("setattr", "delattr") and target and target.split(".")[0] in GUARDED_MODULES:
                    flag("reflection", token, f"{kind}({target}, ...)")
            elif head in ("<builtin>.globals", "builtins.globals"):
                flag("reflection", token, "globals()")
        # Every call along the chain (imports of a computed name, metadata lookups), and every
        # module's __dict__ it reaches.
        _, end = reader.resolve(tokens, index)
        position = index + 1
        while position < end:
            if tokens[position].text in ("[", "("):
                last = closing(tokens, position)
                if tokens[position].text == "(":
                    callee, _ = reader.resolve(tokens[:position], index)
                    call_problems(callee, [part for part in split_top(tokens[position + 1 : last], ",") if part], token, reader, flag, dependency, old_api)
                position = last + 1
            elif tokens[position].text == "." and position + 1 < end:
                attribute = tokens[position + 1].text
                if attribute in WARNING_ATTRS:
                    flag("warnings", token, "." + attribute)
                if attribute == "__dict__" and reader.is_module(tokens[index:position]):
                    base, _ = reader.resolve(tokens[index:position], 0)
                    flag("reflection", token, f"{base}.__dict__")
                position += 2
            else:
                position += 1
    # Strings, folded: each run from a literal (or chr/str) as far as a string expression goes.
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.kind == "string" or (token.kind == "name" and token.text in ("chr", "str", "codecs") and index + 1 < len(tokens) and tokens[index + 1].text in ("(", ".")):
            end = string_extent(tokens, index)
            value = reader.fold(tokens[index:end])
            if value is None and token.kind == "string":
                run = index
                while run < len(tokens) and tokens[run].kind == "string":
                    run += 1
                value = reader.fold(tokens[index:run])
            if value is not None:
                rule = string_rule(value)
                if rule and any(on_added(item) for item in tokens[index:end]):
                    flag(rule, token, repr(value))
            index = max(end, index + 1)
            continue
        index += 1
    # Assignment and deletion targets.
    targets = []
    if texts[0] == "del":
        targets = split_top(tokens[1:], ",")
    else:
        depth = 0
        for position, item in enumerate(tokens):
            if item.kind == "op" and item.text in OPENING:
                depth += 1
            elif item.kind == "op" and item.text in CLOSING:
                depth -= 1
            elif depth == 0 and item.kind == "op" and item.text.endswith("=") and item.text not in ("==", "!=", "<=", ">="):
                targets = split_top(tokens[:position], ",")
                break
    for target in targets:
        if not target or not any(on_added(item) for item in target) or target[0].kind != "name":
            continue
        if target[-1].text == "]":
            opening = next((position for position in range(len(target)) if target[position].text == "[" and closing(target, position) == len(target) - 1), None)
            base, end = reader.resolve(target[:opening], 0) if opening else (None, 0)
            if base and end == opening:
                if base.endswith(".__dict__") and is_dependency(base):
                    flag("patches-dependency", target[0], f"{base}[...] =")
                else:
                    rule = path_rule(base, dependency, old_api)
                    if rule:
                        flag(rule, target[0], base)
        elif len(target) > 2 and target[-2].text == ".":
            base, end = reader.resolve(target[:-2], 0)
            if base and end == len(target) - 2:
                if is_dependency(base):
                    flag("patches-dependency", target[0], f"{base}.{target[-1].text} =")
                elif is_warnings_module(base):
                    flag("warnings", target[0], f"{base}.{target[-1].text} =")
                else:
                    rule = path_rule(f"{base}.{target[-1].text}", dependency, old_api)
                    if rule:
                        flag(rule, target[0], f"{base}.{target[-1].text}")
    return found


def call_problems(callee, arguments, token, reader, flag, dependency, old_api):
    """What a call to ``callee`` with ``arguments`` (token lists) gives away."""
    if callee in IMPORTERS:
        name = reader.fold(arguments[0]) if arguments else None
        if name is None:
            flag("import-system", token, f"{callee.replace('<builtin>.', '')}() of a computed name")
        elif not path_rule(name, dependency, old_api) and callee.endswith("__import__"):
            flag("import-system", token, f"__import__({name!r})")
    elif callee and any(starts(callee, prefix) for prefix in METADATA) and callee.split(".")[-1] in METADATA_CALLS:
        name = reader.fold(arguments[0]) if arguments else None
        if name is None or canonical_name(name) in {canonical_name(item) for item in dependency}:
            flag("version-sniff", token, f"{callee}({name!r})" if name else f"{callee}() of a computed name")


def string_extent(tokens, index):
    """Where a string expression starting at ``index`` ends: literals, ``+``, calls and subscripts on
    them, ``chr(...)``/``str(...)``, parentheses."""
    end, operand = index, True
    while end < len(tokens):
        token = tokens[end]
        if operand:
            if token.kind == "string":
                while end < len(tokens) and tokens[end].kind == "string":
                    end += 1
            elif token.kind == "name" and token.text in ("chr", "str", "codecs") and end + 1 < len(tokens) and tokens[end + 1].text in ("(", "."):
                while end < len(tokens) and tokens[end].text != "(":
                    end += 1
                end = closing(tokens, end) + 1 if end < len(tokens) else end
            elif token.text == "(":
                end = closing(tokens, end) + 1
            else:
                break
            operand = False
        elif token.text == "." and end + 2 < len(tokens) and tokens[end + 2].text == "(":
            end = closing(tokens, end + 2) + 1
        elif token.text == "[":
            end = closing(tokens, end) + 1
        elif token.text == "+" and end + 1 < len(tokens):
            end += 1
            operand = True
        else:
            break
    return end - 1 if operand and end > index + 1 and tokens[end - 1].text == "+" else end


def code_problems(before, after, dependency, old_api=()):
    """``[(line, rule, detail)]``, one per line and rule, for the code ``after`` adds to ``before``
    (both bytes; ``before`` empty for a new file)."""
    added = {number for number, _ in added_with_numbers(python_lines(before), python_lines(after))}
    if not added:
        return []
    logical = statements(tokenize(after.decode("utf-8", errors="replace")))
    reader = Reader(logical)
    first = {}
    for tokens in logical:
        if any(any(line in added for line in range(token.line, token.last + 1)) for token in tokens):
            for line, rule, detail in statement_problems(tokens, reader, added, tuple(dependency), tuple(old_api)):
                first.setdefault((line, rule), detail)
    return [(line, rule, detail) for (line, rule), detail in sorted(first.items())]


def scan(root, changed, entry):
    """``path:line: rule (detail)`` for every shim in the code the changed ``.py`` files add, at most
    30; the rules the instance exempts are left out."""
    root = Path(root)
    exempt = set(entry.get("shim_exempt", []))
    found = []
    for item in changed:
        rel = item["path"]
        if item["status"] == "deleted" or not rel.endswith(".py"):
            continue
        for line, rule, detail in code_problems(pristine_bytes(root, item), (root / rel).read_bytes(), entry["import_names"], entry.get("old_api", [])):
            if rule in exempt:
                continue
            found.append(f"{rel}:{line}: {rule} ({detail})")
            if len(found) >= MAX_FOUND:
                return found
    return found


def recorded_problems(records, entry):
    """The judge's own reading of the code (``plugin.shims``, with ``ast``), as it recorded it, less
    the rules the instance exempts."""
    exempt = set(entry.get("shim_exempt", []))
    return [f"{item['path']}:{item['line']}: {item['rule']} ({item['detail']})" for item in records if isinstance(item, dict) and item.get("rule") not in exempt]


def pristine_manifest(root):
    """The pristine record start_upgrade wrote: ``{"instance", "tree_sha256", "files": {path: sha256}}``,
    or None when it is missing or unreadable."""
    path = Path(root) / ".judge" / "pristine.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        return None
    return data
