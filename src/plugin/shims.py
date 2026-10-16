"""The judge's reading of the code the change adds, with ``ast`` (the verifier may not import it; it
reads the tokens instead, ``verifier.shims``). Same rules, same words: names resolve through the
module's imports and simple aliases, constant strings fold, ``getattr``, ``vars``, ``__dict__``,
``import_module``, ``__import__`` and ``sys.modules[...]`` are followed when their names fold, and every
node on an added line is checked with :func:`verifier.shims.path_rule` and
:func:`verifier.shims.string_rule`. The judge records every finding in the judgement; the verifier
leaves out the rules the instance exempts and fails no_shims on the rest.
"""

from __future__ import annotations

import ast
import builtins
import codecs
import warnings
from pathlib import Path

from verifier.shims import (
    GUARDED_MODULES,
    IMPORTERS,
    METADATA,
    METADATA_CALLS,
    REFLECTORS,
    WARNING_ATTRS,
    added_with_numbers,
    is_warnings_module,
    path_rule,
    pristine_bytes,
    python_lines,
    starts,
    string_rule,
)
from verifier.versions import canonical_name

MAX_FOUND = 100
BUILTIN_NAMES = frozenset(dir(builtins)) | {"__builtins__"}
CASE_METHODS = ("lower", "upper", "strip", "lstrip", "rstrip", "title", "casefold", "capitalize", "swapcase")


class Reader:
    """What the names in one module refer to (``warnings``, ``sys.modules``, ``httpx.Client``; a builtin
    used by its name is ``<builtin>.getattr``), and the strings its expressions always evaluate to."""

    def __init__(self, tree: ast.AST):
        self.bound: dict[str, str] = {}
        self.modules: set[str] = set()  # names bound by ``import``: certainly modules
        self.local: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name.split(".")[0]
                    self.bound[name] = alias.name if alias.asname else name
                    self.modules.add(name)
            elif isinstance(node, ast.ImportFrom):
                base = "." * node.level + (node.module or "")
                for alias in node.names:
                    if alias.name != "*":
                        self.bound[alias.asname or alias.name] = f"{base}.{alias.name}" if base and not base.endswith(".") else base + alias.name
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.local.add(node.name)
            elif isinstance(node, ast.arg):
                self.local.add(node.arg)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                self.local.add(node.id)
        for _ in range(3):  # simple aliases, a few levels deep: x = warnings; f = getattr(x, "simplefilter")
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    targets, value = node.targets, node.value
                elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
                    targets, value = [node.target], node.value
                else:
                    continue
                path = self.resolve(value)
                if path:
                    for target in targets:
                        if isinstance(target, ast.Name) and target.id not in self.modules:
                            self.bound[target.id] = path

    def resolve(self, node: ast.AST, depth: int = 0) -> str | None:
        """The dotted name ``node`` refers to, or None when it cannot be told."""
        if depth > 25:
            return None
        if isinstance(node, ast.Name):
            if node.id in self.bound:
                return self.bound[node.id]
            if node.id in BUILTIN_NAMES and node.id not in self.local:
                return "<builtin>." + node.id
            return None
        if isinstance(node, ast.Attribute):
            base = self.resolve(node.value, depth + 1)
            return f"{base}.{node.attr}" if base else None
        if isinstance(node, ast.NamedExpr):
            return self.resolve(node.value, depth + 1)
        if isinstance(node, ast.Call):
            func = self.resolve(node.func, depth + 1)
            if func in ("<builtin>.getattr", "builtins.getattr") and len(node.args) >= 2:
                base, name = self.resolve(node.args[0], depth + 1), self.fold(node.args[1])
                return f"{base}.{name}" if base and name else None
            if func in IMPORTERS and node.args:
                return self.fold(node.args[0])
            if func in ("<builtin>.vars", "builtins.vars") and node.args:
                base = self.resolve(node.args[0], depth + 1)
                return f"{base}.__dict__" if base else None
            return None
        if isinstance(node, ast.Subscript):
            base, key = self.resolve(node.value, depth + 1), self.fold(node.slice)
            if base and key:
                if base == "sys.modules":
                    return key
                if base.endswith(".__dict__"):
                    return f"{base[: -len('.__dict__')]}.{key}"
        return None

    def is_module(self, node: ast.AST, path: str | None) -> bool:
        """Whether ``node`` (resolving to ``path``) is a module object rather than something in one."""
        if isinstance(node, ast.Name) and node.id in self.modules:
            return True
        if path in GUARDED_MODULES or path == "builtins":
            return True
        if isinstance(node, ast.Call) and self.resolve(node.func) in IMPORTERS:
            return True
        return isinstance(node, ast.Subscript) and self.resolve(node.value) == "sys.modules"

    def fold(self, node: ast.AST, depth: int = 0) -> str | None:
        """The string ``node`` always evaluates to, or None."""
        if depth > 40:
            return None
        if isinstance(node, ast.Constant):
            return node.value if isinstance(node.value, str) else None
        if isinstance(node, ast.BinOp):
            return self.fold_operator(node, depth)
        if isinstance(node, ast.JoinedStr):
            parts = []
            for value in node.values:
                if isinstance(value, ast.Constant):
                    parts.append(str(value.value))
                elif isinstance(value, ast.FormattedValue) and value.conversion == -1 and value.format_spec is None and isinstance(value.value, ast.Constant) and isinstance(value.value.value, str):
                    parts.append(value.value.value)  # a field that is a string literal, as the token reader folds it
                else:
                    return None
            return "".join(parts)
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
            return self.fold_slice(node, depth)
        if isinstance(node, ast.Call):
            return self.fold_call(node, depth)
        return None

    def fold_operator(self, node: ast.BinOp, depth: int) -> str | None:
        left = self.fold(node.left, depth + 1)
        if left is None:
            return None
        if isinstance(node.op, ast.Add):
            right = self.fold(node.right, depth + 1)
            return left + right if right is not None else None
        if isinstance(node.op, ast.Mult) and isinstance(node.right, ast.Constant) and isinstance(node.right.value, int) and 0 <= node.right.value <= 64:
            return left * node.right.value
        if isinstance(node.op, ast.Mod):
            values = node.right.elts if isinstance(node.right, ast.Tuple) else [node.right]
            folded = [self.fold(value, depth + 1) for value in values]
            if all(value is not None for value in folded):
                try:
                    return left % tuple(folded)
                except (TypeError, ValueError):
                    return None
        return None

    def fold_slice(self, node: ast.Subscript, depth: int) -> str | None:
        owner = self.fold(node.value, depth + 1)
        if owner is None:
            return None
        bounds = []
        for part in (node.slice.lower, node.slice.upper, node.slice.step):
            if part is None:
                bounds.append(None)
                continue
            try:
                number = ast.literal_eval(part)
            except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
                return None
            if not isinstance(number, int) or (number == 0 and part is node.slice.step):
                return None
            bounds.append(number)
        return owner[slice(*bounds)]

    def fold_call(self, node: ast.Call, depth: int) -> str | None:
        func = node.func
        if isinstance(func, ast.Attribute):
            owner = self.fold(func.value, depth + 1)
            if owner is not None:
                if func.attr == "join" and len(node.args) == 1 and isinstance(node.args[0], (ast.List, ast.Tuple)):
                    items = [self.fold(item, depth + 1) for item in node.args[0].elts]
                    return owner.join(items) if all(item is not None for item in items) else None
                if func.attr in CASE_METHODS and not node.args:
                    return getattr(owner, func.attr)()
                if func.attr == "replace" and len(node.args) == 2:
                    old, new = self.fold(node.args[0], depth + 1), self.fold(node.args[1], depth + 1)
                    return owner.replace(old, new) if old is not None and new is not None else None
                if func.attr == "format" and not node.keywords:
                    values = [self.fold(item, depth + 1) for item in node.args]
                    if all(value is not None for value in values):
                        try:
                            return owner.format(*values)
                        except (IndexError, KeyError, ValueError):
                            return None
                return None
        name = self.resolve(func)
        if name in ("<builtin>.chr", "builtins.chr") and len(node.args) == 1:
            value = node.args[0]
            if isinstance(value, ast.Constant) and isinstance(value.value, int) and 0 <= value.value < 0x110000:
                return chr(value.value)
        if name in ("<builtin>.str", "builtins.str") and len(node.args) == 1:
            return self.fold(node.args[0], depth + 1)
        if name in ("codecs.decode", "codecs.encode") and len(node.args) == 2:
            text, codec = self.fold(node.args[0], depth + 1), self.fold(node.args[1], depth + 1)
            if text is not None and codec and codec.replace("_", "").lower() == "rot13":
                return codecs.decode(text, "rot13")
        return None


class Checker:
    def __init__(self, tree: ast.AST, added: set[int], dependency: list[str], old_api: list[str]):
        self.reader = Reader(tree)
        self.added = added
        self.dependency = tuple(dependency)
        self.old_api = tuple(old_api)
        self.canonical = {canonical_name(name) for name in dependency}
        self.found: list[tuple[int, str, str]] = []

    def on_added(self, node: ast.AST) -> bool:
        first = getattr(node, "lineno", None)
        if first is None:
            return False
        last = getattr(node, "end_lineno", None) or first
        return any(line in self.added for line in range(first, last + 1))

    def flag(self, rule: str, node: ast.AST, detail: str) -> None:
        self.found.append((node.lineno, rule, detail[:80]))

    def is_dependency(self, path: str | None) -> bool:
        return bool(path) and any(starts(path, name) for name in self.dependency)

    def check_path(self, path: str | None, node: ast.AST) -> bool:
        rule = path_rule(path, self.dependency, self.old_api)
        if rule:
            self.flag(rule, node, path)
        return bool(rule)

    def check_call(self, node: ast.Call) -> None:
        reader = self.reader
        func = reader.resolve(node.func)
        kind = func.rsplit(".", 1)[-1] if func and func.startswith(("<builtin>.", "builtins.")) else ""
        if kind in REFLECTORS and node.args:
            # Every rule that applies, as the token reader names them.
            target = reader.resolve(node.args[0])
            name = reader.fold(node.args[1]) if len(node.args) > 1 else None
            if target and name:
                self.check_path(f"{target}.{name}", node)
            if kind in ("setattr", "delattr") and self.is_dependency(target):
                self.flag("patches-dependency", node, f"{kind}({target}, ...)")
            if kind in ("setattr", "delattr") and is_warnings_module(target):
                self.flag("warnings", node, f"{kind}({target}, ...)")
            if kind != "hasattr" and reader.is_module(node.args[0], target):
                self.flag("reflection", node, f"{kind}() on the module {target}")
            elif kind in ("setattr", "delattr") and target and target.split(".")[0] in GUARDED_MODULES:
                self.flag("reflection", node, f"{kind}({target}, ...)")
            return
        if func in ("<builtin>.globals", "builtins.globals"):
            self.flag("reflection", node, "globals()")
            return
        if func in IMPORTERS:
            name = reader.fold(node.args[0]) if node.args else None
            if name is None:
                self.flag("import-system", node, f"{func.replace('<builtin>.', '')}() of a computed name")
            elif not self.check_path(name, node) and func.endswith("__import__"):
                self.flag("import-system", node, f"__import__({name!r})")
            return
        if func and any(starts(func, prefix) for prefix in METADATA) and func.rsplit(".", 1)[-1] in METADATA_CALLS:
            name = reader.fold(node.args[0]) if node.args else None
            if name is None or canonical_name(name) in self.canonical:
                self.flag("version-sniff", node, f"{func}({name!r})" if name else f"{func}() of a computed name")
            return
        if func and func.endswith((".__setattr__", ".__delattr__")) and node.args and self.is_dependency(reader.resolve(node.args[0])):
            self.flag("patches-dependency", node, func.rsplit(".", 1)[-1])

    def check_target(self, target: ast.AST) -> None:
        if isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                self.check_target(item)
            return
        if isinstance(target, ast.Starred):
            self.check_target(target.value)
            return
        if not self.on_added(target):
            return
        if isinstance(target, ast.Attribute):
            base = self.reader.resolve(target.value)
            if self.is_dependency(base):
                self.flag("patches-dependency", target, f"{base}.{target.attr} =")
            elif is_warnings_module(base):
                self.flag("warnings", target, f"{base}.{target.attr} =")
            elif base:
                self.check_path(f"{base}.{target.attr}", target)
        elif isinstance(target, ast.Subscript):
            base = self.reader.resolve(target.value)
            if base and base.endswith(".__dict__") and self.is_dependency(base):
                self.flag("patches-dependency", target, f"{base}[...] =")
            elif base:
                self.check_path(base, target)
            self.check_path(self.reader.resolve(target), target)  # what is written: sys.modules["pydantic.v1"]

    def run(self, tree: ast.AST) -> list[tuple[int, str, str]]:
        reader = self.reader
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and self.on_added(node):
                for alias in node.names:
                    self.check_path(alias.name, node)
            elif isinstance(node, ast.ImportFrom) and self.on_added(node) and node.level == 0 and node.module:
                if not self.check_path(node.module, node):
                    for alias in node.names:
                        if alias.name != "*" and self.check_path(f"{node.module}.{alias.name}", node):
                            break
            elif isinstance(node, (ast.Name, ast.Attribute)) and isinstance(node.ctx, ast.Load) and self.on_added(node):
                self.check_path(reader.resolve(node), node)
                if isinstance(node, ast.Attribute) and node.attr in WARNING_ATTRS:
                    self.flag("warnings", node, "." + node.attr)
                if isinstance(node, ast.Attribute) and node.attr == "__dict__" and reader.is_module(node.value, reader.resolve(node.value)):
                    self.flag("reflection", node, f"{reader.resolve(node.value)}.__dict__")
            elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load) and self.on_added(node):
                self.check_path(reader.resolve(node), node)
            elif isinstance(node, ast.Call) and self.on_added(node.func):
                self.check_call(node)
            if isinstance(node, (ast.Assign, ast.Delete)):
                for target in node.targets:
                    self.check_target(target)
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                self.check_target(node.target)
            if isinstance(node, (ast.Constant, ast.BinOp, ast.JoinedStr, ast.Call, ast.Subscript)) and self.on_added(node):
                text = reader.fold(node)
                rule = string_rule(text) if text is not None else None
                if rule:
                    self.flag(rule, node, repr(text.strip()))
        return self.found


def code_problems(before: bytes, after: bytes, dependency: list[str], old_api: list[str] = ()) -> list[tuple[int, str, str]]:
    """``[(line, rule, detail)]``, one per line and rule, for the code ``after`` adds to ``before``
    (both bytes; ``before`` empty for a new file). A file that does not parse is a problem of its own."""
    added = {number for number, _ in added_with_numbers(python_lines(before), python_lines(after))}
    if not added:
        return []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # invalid escapes in the scanned code are not ours to report
            tree = ast.parse(after)
    except (SyntaxError, ValueError) as error:
        return [(getattr(error, "lineno", 0) or 0, "unreadable", f"not valid Python: {error}")]
    first: dict[tuple[int, str], str] = {}
    for line, rule, detail in Checker(tree, added, list(dependency), list(old_api)).run(tree):
        first.setdefault((line, rule), detail)
    return [(line, rule, detail) for (line, rule), detail in sorted(first.items())]


def scan(root: Path, changed: list[dict], entry: dict) -> list[dict]:
    """Every finding (exempt rules too, at most 100) in the code the changed ``.py`` files add, as
    ``{"path", "line", "rule", "detail"}``: what the judge records."""
    found = []
    for item in changed:
        rel = item["path"]
        if item["status"] == "deleted" or not rel.endswith(".py"):
            continue
        for line, rule, detail in code_problems(pristine_bytes(root, item), (Path(root) / rel).read_bytes(), entry["import_names"], entry.get("old_api", [])):
            found.append({"path": rel, "line": line, "rule": rule, "detail": detail})
            if len(found) >= MAX_FOUND:
                return found
    return found
