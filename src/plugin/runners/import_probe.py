"""The import probe, run by the judge with the project's own interpreter (never imported by the plugin).

    python import_probe.py project <request.json> <out.json>
    python import_probe.py reference <request.json> <project-out.json> <out.json>

``project`` imports the project's modules (``request["modules"]``, its top-level packages first) and
records the interpreter as that leaves it: the warnings filters and the warnings module, the import
hooks, every loaded module of the dependency (``request["dependency"]``) with its attributes described,
and every object of the project's own (by its module, or the file its code is in) that now sits in one
of the dependency's modules or classes. ``reference`` is a fresh interpreter that imports every module
the project run loaded except the project's own, looks up the attributes the project run saw on the
dependency's modules (so lazily created ones exist here too), records the same, and writes what
differs: what importing the project did. Descriptions name modules and qualified names, never paths.
"""

import builtins
import functools
import importlib
import json
import os
import sys
import types
import warnings

# Attributes the interpreter itself adds as code runs: a module's registry of warnings shown, its
# annotations (created on first access).
BOOKKEEPING = frozenset({"__warningregistry__", "__annotations__"})
CALLABLE_TYPES = (
    types.BuiltinFunctionType,
    types.MethodType,
    types.WrapperDescriptorType,
    types.MethodDescriptorType,
    types.MethodWrapperType,
    types.ClassMethodDescriptorType,
    types.GetSetDescriptorType,
    types.MemberDescriptorType,
)
API_KINDS = ("function ", "class ", "module ", "wraps ", "builtin ")
PLAIN = (bool, int, float, str, type(None))
PACKAGES = []
ROOTS = []


def _ours(name, tops):
    return any(name == top or name.startswith(top + ".") for top in tops)


def _inner(value, depth=0):
    """The function or class behind a wrapper (staticmethod, property, functools.wraps, partial)."""
    if depth > 4:
        return value
    if isinstance(value, (staticmethod, classmethod)):
        return _inner(value.__func__, depth + 1)
    if isinstance(value, property):
        return _inner(value.fget, depth + 1)
    if isinstance(value, functools.partial):
        return _inner(value.func, depth + 1)
    wrapped = getattr(value, "__wrapped__", None) if callable(value) and not isinstance(value, type) else None
    if wrapped is not None and wrapped is not value:
        return _inner(wrapped, depth + 1)
    return value


def from_project(value):
    """Whether ``value`` is the project's own: defined in its modules or in its files."""
    for item in {id(value): value, id(_inner(value)): _inner(value)}.values():
        if isinstance(item, types.FunctionType):
            filename = os.path.realpath(item.__code__.co_filename)
            if any(filename.startswith(root) for root in ROOTS) or _ours(str(item.__module__), PACKAGES):
                return True
        elif isinstance(item, types.ModuleType):
            if _ours(str(getattr(item, "__name__", "")), PACKAGES):
                return True
        elif isinstance(item, type):
            if _ours(str(item.__module__), PACKAGES):
                return True
        elif item is not None and _ours(str(type(item).__module__), PACKAGES):
            return True
    return False


def describe(value):
    """What ``value`` is, in words two interpreters agree on when it is the same thing. Plain values
    (numbers, strings, containers, instances) are described by type only: libraries change their own
    counters and caches as they run."""
    mark = " [project]" if from_project(value) else ""
    if isinstance(value, types.ModuleType):
        return f"module {getattr(value, '__name__', '?')}{mark}"
    if isinstance(value, types.FunctionType):
        return f"function {value.__module__}.{value.__qualname__}{mark}"
    if isinstance(value, type):
        return f"class {value.__module__}.{value.__qualname__}{mark}"
    if isinstance(value, CALLABLE_TYPES):
        return f"builtin {getattr(value, '__module__', None)}.{getattr(value, '__qualname__', getattr(value, '__name__', '?'))}{mark}"
    inner = _inner(value)
    if inner is not value:
        return "wraps " + describe(inner)
    return f"object {type(value).__module__}.{type(value).__qualname__}{mark}"


def filter_text(item):
    action, message, category, module, lineno = item
    return f"{action}:{getattr(message, 'pattern', message) or ''}:{category.__module__}.{category.__qualname__}:{getattr(module, 'pattern', module) or ''}:{lineno}"


def snapshot(dependency, *, injections):
    modules = {}
    injected = []
    for name, module in list(sys.modules.items()):
        if not _ours(name, dependency) or not isinstance(module, types.ModuleType):
            continue
        try:
            namespace = dict(vars(module))
        except TypeError:
            continue
        modules[name] = {
            "file": os.path.realpath(str(getattr(module, "__file__", "") or "")),
            "attrs": {attr: describe(value) for attr, value in namespace.items() if attr not in BOOKKEEPING},
        }
        if not injections:
            continue
        for attr, value in namespace.items():
            if from_project(value):
                injected.append(f"puts the project's {describe(value)} into {name}.{attr}")
            elif isinstance(value, type) and value.__module__ == name:
                try:
                    members = dict(vars(value))
                except TypeError:
                    continue
                for member, item in members.items():
                    if from_project(item):
                        injected.append(f"puts the project's {describe(item)} into {name}.{attr}.{member}")
    return {
        "filters": [filter_text(item) for item in warnings.filters],
        "warnings": {attr: describe(value) + (f" {value!r}" if isinstance(value, PLAIN) else "") for attr, value in vars(warnings).items() if attr not in ("filters", "_filters_version") and attr not in BOOKKEEPING},
        "meta_path": [describe(finder if isinstance(finder, type) else type(finder)) for finder in sys.meta_path],
        "path_hooks": [describe(hook) for hook in sys.path_hooks],
        "import": describe(builtins.__import__),
        "dependency": modules,
        "injected": sorted(set(injected)),
    }


def differences(project, reference):
    found = list(project["injected"])
    theirs = list(reference["filters"])
    for item in project["filters"]:
        if item in theirs:
            theirs.remove(item)
        else:
            found.append("adds the warning filter " + item)
    found += ["removes the warning filter " + item for item in theirs]
    for attr in sorted(set(project["warnings"]) | set(reference["warnings"])):
        if project["warnings"].get(attr) != reference["warnings"].get(attr):
            found.append(f"changes warnings.{attr}")
    for key, label in (("meta_path", "sys.meta_path"), ("path_hooks", "sys.path_hooks"), ("import", "__import__")):
        if project[key] != reference[key]:
            found.append("changes " + label)
    for name, seen in sorted(project["dependency"].items()):
        clean = reference["dependency"].get(name)
        if clean is None:
            found.append(f"loads {name}, which does not import on its own")
            continue
        if seen["file"] != clean["file"]:
            found.append(f"loads {name} from elsewhere than the environment does")
        for attr in sorted(set(seen["attrs"]) | set(clean["attrs"])):
            mine, theirs_now = seen["attrs"].get(attr), clean["attrs"].get(attr)
            if mine == theirs_now:
                continue
            if mine is None:
                found.append(f"removes {name}.{attr}")
            elif theirs_now is None:
                found.append(f"adds {name}.{attr} ({mine})")
            elif mine.startswith(API_KINDS) or theirs_now.startswith(API_KINDS):
                found.append(f"replaces {name}.{attr} ({mine}, not {theirs_now})")
    return sorted(set(found))


def project_run(request, out):
    imported, errors = [], {}
    for name in request["modules"]:
        try:
            importlib.import_module(name)
            imported.append(name)
        except BaseException as error:  # noqa: BLE001 - a SystemExit at import is a finding too
            errors[name] = f"{type(error).__name__}: {str(error)[:200]}"
    loaded = [name for name in list(sys.modules) if not _ours(name, PACKAGES) and name not in ("__main__", "__mp_main__")]
    with open(out, "w", encoding="utf-8") as handle:
        json.dump({"imported": imported, "errors": errors, "loaded": loaded, "state": snapshot(request["dependency"], injections=True)}, handle)


def reference_run(request, seen_path, out):
    with open(seen_path, encoding="utf-8") as handle:
        seen = json.load(handle)
    for name in seen["loaded"]:
        if name not in sys.modules:
            try:
                importlib.import_module(name)
            except BaseException:  # noqa: BLE001, S110 - a module that does not import alone is reported below
                pass
    for name, info in seen["state"]["dependency"].items():
        module = sys.modules.get(name)
        if module is None:
            continue
        for attr in info["attrs"]:
            if attr not in vars(module):
                try:
                    getattr(module, attr)
                except BaseException:  # noqa: BLE001, S110 - absent here: the project's import made it
                    pass
    found = differences(seen["state"], snapshot(request["dependency"], injections=False))
    with open(out, "w", encoding="utf-8") as handle:
        json.dump({"findings": found, "imported": seen["imported"], "errors": seen["errors"]}, handle)


if __name__ == "__main__":
    mode, request_path = sys.argv[1], sys.argv[2]
    with open(request_path, encoding="utf-8") as handle:
        given = json.load(handle)
    PACKAGES.extend(given["packages"])
    ROOTS.extend(os.path.realpath(root) + os.sep for root in given.get("roots", []))
    if mode == "project":
        project_run(given, sys.argv[3])
    else:
        reference_run(given, sys.argv[3], sys.argv[4])
