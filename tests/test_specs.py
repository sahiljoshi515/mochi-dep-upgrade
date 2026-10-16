"""The spec readers (verifier/specs.py) agree with a real parser of each kind, blank exactly the
requirements region, and refuse what they cannot read; the plugin's reader refuses disagreement."""

from __future__ import annotations

import pytest

from plugin.common import ToolError
from plugin.spec import read
from verifier.specs import read_spec

PEP621 = '[project]\nname = "x"\nrequires-python = ">=3.9"\ndependencies = [\n    "pydantic>=1.8",  # including 2!\n    \'ruamel.yaml>=0.16,<0.18\',\n]\n\n[project.optional-dependencies]\ndev = ["pytest"]\n'
SETUP_CFG = "[metadata]\nname = x\n\n[options]\npackages = find:\ninstall_requires =\n    marshmallow>=3.0\n\n    python-dotenv\npython_requires = >=3.8\n\n[options.extras_require]\ntests = pytest\n"
SETUP_PY = 'from setuptools import setup\nsetup(\n    name="x",\n    install_requires=["httpx>=0.25.0,<0.28.0", "six"],  # the runtime needs\n    python_requires=">=3.8",\n)\n'
REQUIREMENTS = "sqlalchemy >= 1.0\nsix\n# a comment\ntyping; python_version < '3.5'\n"


@pytest.mark.parametrize(
    ("kind", "text", "expected"),
    [
        ("pep621", PEP621, ["pydantic>=1.8", "ruamel.yaml>=0.16,<0.18"]),
        ("setup_cfg", SETUP_CFG, ["marshmallow>=3.0", "python-dotenv"]),
        ("setup_py", SETUP_PY, ["httpx>=0.25.0,<0.28.0", "six"]),
        ("requirements_txt", REQUIREMENTS, ["sqlalchemy >= 1.0", "six", "typing; python_version < '3.5'"]),
    ],
)
def test_each_kind_reads_like_its_real_parser(kind: str, text: str, expected: list[str]):
    requirements, blanked = read_spec(kind, text)
    assert requirements == expected
    assert read(kind, text, name="spec")[0] == expected
    if kind != "requirements_txt":
        for item in expected:
            assert item not in blanked
        assert ("python_requires" in blanked) or ("requires-python" in blanked) or ("python_requires" not in text)


def test_changing_only_the_requirements_keeps_the_blanked_text():
    changed = SETUP_PY.replace('"httpx>=0.25.0,<0.28.0"', '"httpx>=0.28"')
    assert read_spec("setup_py", changed)[1] == read_spec("setup_py", SETUP_PY)[1]
    renamed = SETUP_PY.replace('name="x"', 'name="y"')
    assert read_spec("setup_py", renamed)[1] != read_spec("setup_py", SETUP_PY)[1]
    cfg = SETUP_CFG.replace("marshmallow>=3.0", "marshmallow>=4.0")
    assert read_spec("setup_cfg", cfg)[1] == read_spec("setup_cfg", SETUP_CFG)[1]
    pep = PEP621.replace("pydantic>=1.8", "pydantic>=2")
    assert read_spec("pep621", pep)[1] == read_spec("pep621", PEP621)[1]


@pytest.mark.parametrize(
    ("kind", "text"),
    [
        ("setup_py", "setup(install_requires=REQS)\n"),
        ("setup_py", 'setup(install_requires=["a" "b"])\n'),
        ("setup_py", 'setup(install_requires=["a"])\nsetup(install_requires=["b"])\n'),
        ("pep621", "[project]\nname = 'x'\n"),
        ("setup_cfg", "[metadata]\nname = x\n"),
        ("requirements_txt", "-r other.txt\n"),
    ],
)
def test_unreadable_specs_are_refused(kind: str, text: str):
    with pytest.raises(ValueError):
        read_spec(kind, text)


def test_the_plugin_refuses_a_requirement_it_cannot_read():
    with pytest.raises(ToolError):
        read("setup_py", 'setup(install_requires=["httpx>>1"])\n', name="setup.py")
