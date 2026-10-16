"""The shim readers (review F2, R2-N1, R2-N2): the judge's reads the added code with ast, the verifier's
from its tokens. Every spelling of what silences or reroutes warnings, or of the other shims the rules
name, is caught by both; emitting a warning and ordinary migration code are caught by neither; both
name the same rules on the same lines; only added lines count."""

from __future__ import annotations

import pytest

from plugin.shims import code_problems as ast_problems
from verifier.shims import code_problems as token_problems
from verifier.shims import python_lines

READERS = {"ast": ast_problems, "tokens": token_problems}

FLAGGED = {
    # Silencing or rerouting warnings, however reached.
    "getattr with concatenation": ("import warnings as _w\ngetattr(_w, 'filter'+'warnings')('ignore')\n", "warnings"),
    "__dict__ subscript": ("import warnings\nwarnings.__dict__['filterwarnings']('ignore')\n", "warnings"),
    "vars() subscript": ("import warnings\nvars(warnings)['simple' 'filter']('ignore')\n", "warnings"),
    "import_module of a built name": ("import importlib\nimportlib.import_module('warn' + 'ings').simplefilter('ignore')\n", "warnings"),
    "renamed from-import": ("from warnings import simplefilter as _q\n_q('ignore')\n", "warnings"),
    "__import__": ("__import__('warnings').filterwarnings('ignore')\n", "warnings"),
    "join and chr": ("import warnings as w\ngetattr(w, ''.join([chr(115), 'implefilter']))('ignore')\n", "warnings"),
    "f-string with a literal field": ("import warnings as w\ngetattr(w, f\"{'filter'}warnings\")('ignore')\n", "warnings"),
    "rot13": ("import codecs, importlib\nimportlib.import_module(codecs.decode('jneavatf', 'rot13')).simplefilter('ignore')\n", "warnings"),
    "reversed slice": ("import importlib\nimportlib.import_module('sgninraw'[::-1]).resetwarnings()\n", "warnings"),
    "escapes": ("import warnings as w\ngetattr(w, 'simple\\x66ilter')('ignore')\n", "warnings"),
    "filters emptied": ("import warnings\nwarnings.filters[:] = []\n", "warnings"),
    "filters added to": ("import warnings\nwarnings.filters.insert(0, ('ignore', None, Warning, None, 0))\n", "warnings"),
    "a filter deleted": ("import warnings\ndel warnings.filters[0]\n", "warnings"),
    "catch_warnings on anything": ("def f(x):\n    return x._module.catch_warnings()\n", "warnings"),
    "catch_warnings recording": ("import warnings\n\n\ndef f(g):\n    with warnings.catch_warnings(record=True):\n        return g()\n", "warnings"),
    "showwarning replaced": ("import warnings\nwarnings.showwarning = lambda *a, **k: None\n", "warnings"),
    "formatwarning replaced": ("import warnings\nwarnings.formatwarning = str\n", "warnings"),
    "showwarning through setattr": ("import warnings\nsetattr(warnings, 'showwarning', print)\n", "warnings"),
    "the default action": ("import warnings\nwarnings.defaultaction = 'ignore'\n", "warnings"),
    "logging's capture": ("import logging\nlogging.captureWarnings(True)\n", "warnings"),
    "logging's warnings": ("import logging\nlogging.warnings.simplefilter('ignore')\n", "warnings"),
    "PYTHONWARNINGS": ("import os\nos.environ['PYTHONWARNINGS'] = 'ignore'\n", "warnings"),
    # The other rules.
    "aliased sys.modules write": ("import sys as _s\n_s.modules['pydantic.v1'] = object()\n", "import-system"),
    "a computed import": ("import importlib\nimportlib.import_module(input())\n", "import-system"),
    "sys.path": ("import sys\nsys.path.insert(0, 'vendor')\n", "import-system"),
    "reload": ("from importlib import reload\nimport pydantic\nreload(pydantic)\n", "import-system"),
    "exec": ("exec('x = 1')\n", "dynamic-code"),
    "eval": ("X = eval('1')\n", "dynamic-code"),
    "globals()": ("globals()['x'] = 1\n", "reflection"),
    "builtins": ("import builtins\nbuiltins.print = None\n", "reflection"),
    "f-string with a variable field": ("import warnings as w\nname = 'filter'\ngetattr(w, f'{name}warnings')('ignore')\n", "reflection"),
    "getattr on the dependency module": ("import pydantic\nX = getattr(pydantic, 'BaseSettings', None)\n", "reflection"),
    "setattr on the dependency": ("import pydantic\nsetattr(pydantic, 'BaseSettings', object)\n", "patches-dependency"),
    "assigning into a dependency class": ("from pydantic import main as m\nm.BaseModel.parse_obj = classmethod(lambda c, o: c(**o))\n", "patches-dependency"),
    "assigning into the dependency": ("import pydantic\npydantic.BaseSettings = dict\n", "patches-dependency"),
    "unittest.mock": ("from unittest import mock\nmock.patch('pydantic.BaseModel')\n", "patches-dependency"),
    "VERSION": ("import pydantic\nV2 = pydantic.VERSION.startswith('2')\n", "version-sniff"),
    "pydantic.version": ("from pydantic.version import VERSION\n", "version-sniff"),
    "metadata version": ("from importlib.metadata import version\nV = version('pydantic')\n", "version-sniff"),
    "metadata version, other spelling": ("import importlib.metadata as md\nV = md.version('Pydantic')\n", "version-sniff"),
    "sys.argv": ("import sys\nT = sys.argv[0].endswith('pytest')\n", "test-sniff"),
    "PYTEST_CURRENT_TEST": ("import os\nT = os.environ.get('PYTEST_CURRENT_TEST')\n", "test-sniff"),
    "pytest imported": ("import pytest\n", "test-sniff"),
    "the old API copy": ("from pydantic.v1 import BaseModel\n", "old-api"),
}

# Emitting a warning is not a shim (R2-N1): a migration may add its own deprecation notice.
EMITTING = {
    "warnings.warn": "import warnings\n\n\ndef old(x):\n    warnings.warn('old() is deprecated; use new()', DeprecationWarning, stacklevel=2)\n    return x\n",
    "a renamed warn": "from warnings import warn as _warn\n_warn('legacy', FutureWarning)\n",
    "warn_explicit": "import warnings\nwarnings.warn_explicit('legacy', UserWarning, 'x.py', 1)\n",
    "a deprecation category of the project's": "class LegacyWarning(DeprecationWarning):\n    pass\n",
    "formatting a warning": "import warnings\nTEXT = warnings.formatwarning('m', UserWarning, 'f.py', 1)\n",
    "importing the module only": "import warnings\n",
    "a warning through getattr's name": "import warnings\nwarnings.warn(getattr(object, '__doc__'))\n",
}

CLEAN = {
    "a plain migration": "import pydantic\n\n\nclass M(pydantic.BaseModel):\n    x: int = pydantic.Field(default=1)\n",
    "a class's own __dict__": "def table(cls):\n    return cls.__dict__['__table__']\n",
    "getattr on an object": "def get(obj, name):\n    return getattr(obj, name)\n",
    "re.compile": "import re\nP = re.compile('x')\n",
    "a message about warnings": "MESSAGE = 'Deprecation warnings are shown'\n",
    "self.warnings": "class A:\n    def f(self):\n        return self.warnings\n",
    "the Python version": "import sys\nPY311 = sys.version_info >= (3, 11)\n",
    "object.__setattr__ on self": "class A:\n    def __init__(self):\n        object.__setattr__(self, 'x', 1)\n",
    "feature detection with hasattr": "import pydantic\nV2 = hasattr(pydantic, 'field_validator')\n",
    "a local named compile": "def compile(x):\n    return x\n\n\nY = compile(1)\n",
    "a local named warnings": "def f():\n    warnings = []\n    warnings.append('x')\n    return warnings\n",
}

# Everything above, and the review's named evasions (its own fuzz list was not left on disk): the
# two readers must name the same rules on the same lines for each.
REVIEW = {
    "review: the literal filter": "import warnings\nwarnings.filterwarnings('ignore')\n",
    "review: getattr and concatenation": "import warnings as _w\ngetattr(_w, 'filter'+'warnings')('ignore')\n",
    "review: __dict__": "import warnings\nwarnings.__dict__['filterwarnings']('ignore')\n",
    "review: an aliased sys": "import sys as _s\n_s.modules['pydantic.v1'] = _s.modules['pydantic']\n",
    "review: import_module": "import importlib\nimportlib.import_module('warn' + 'ings').simplefilter('ignore')\n",
    "review: a version sniff": "from importlib.metadata import version as _v\nNEW = _v('httpx').split('.')[0] != '0'\n",
    "review: a dependency setattr": "import httpx\nsetattr(httpx, 'LegacyName', object)\n",
}
PARITY = {**{name: code for name, (code, _) in FLAGGED.items()}, **EMITTING, **CLEAN, **REVIEW}


@pytest.mark.parametrize("reader", sorted(READERS))
@pytest.mark.parametrize("name", sorted(FLAGGED))
def test_each_spelling_is_caught(name: str, reader: str):
    code, rule = FLAGGED[name]
    found = READERS[reader](b"", code.encode(), ["pydantic"], ["pydantic.v1"])
    assert rule in {item[1] for item in found}, found


@pytest.mark.parametrize("reader", sorted(READERS))
@pytest.mark.parametrize("name", sorted(EMITTING))
def test_emitting_a_warning_is_not_a_shim(name: str, reader: str):
    assert READERS[reader](b"", EMITTING[name].encode(), ["pydantic"], ["pydantic.v1"]) == []


@pytest.mark.parametrize("reader", sorted(READERS))
@pytest.mark.parametrize("name", sorted(CLEAN))
def test_ordinary_code_is_not_a_shim(name: str, reader: str):
    assert READERS[reader](b"", CLEAN[name].encode(), ["pydantic"], ["pydantic.v1"]) == []


@pytest.mark.parametrize("name", sorted(PARITY))
def test_both_readers_name_the_same_rules_on_the_same_lines(name: str):
    code = PARITY[name].encode()
    ast_found = {(line, rule) for line, rule, _ in ast_problems(b"", code, ["pydantic", "httpx"], ["pydantic.v1"])}
    token_found = {(line, rule) for line, rule, _ in token_problems(b"", code, ["pydantic", "httpx"], ["pydantic.v1"])}
    assert ast_found == token_found


def test_the_dict_spelling_names_reflection_and_warnings_in_both():
    # R2-N2's example: the same construct, the same two rules.
    code = b"import warnings\nwarnings.__dict__['filterwarnings']('ignore')\n"
    for read in READERS.values():
        assert {rule for _, rule, _ in read(b"", code, ["x"])} == {"reflection", "warnings"}


@pytest.mark.parametrize("reader", sorted(READERS))
def test_only_added_lines_count(reader: str):
    before = b"import warnings\nwarnings.simplefilter('ignore')\n\n\ndef f():\n    return 1\n"
    after = before.replace(b"return 1", b"return 2")
    assert READERS[reader](before, after, ["pydantic"]) == []
    found = READERS[reader](before, after + b"warnings.resetwarnings()\n", ["pydantic"])
    assert [(line, rule) for line, rule, _ in found] == [(7, "warnings")]


@pytest.mark.parametrize("reader", sorted(READERS))
def test_lines_are_numbered_as_python_numbers_them(reader: str):
    # A form feed is whitespace to Python, a line break to str.splitlines.
    assert python_lines(b"a = 1\n\x0cb = 2\r\nc = 3\rd = 4\n") == ["a = 1", "\x0cb = 2", "c = 3", "d = 4"]
    found = READERS[reader](b"a = 1\n\x0c\nb = 2\n", b"a = 1\n\x0c\nb = 2\nexec('x')\n", ["x"])
    assert [line for line, _, _ in found] == [4]


def test_code_that_does_not_parse_is_a_problem_for_the_judge():
    assert ast_problems(b"", b"def f(:\n", ["x"])[0][1] == "unreadable"
