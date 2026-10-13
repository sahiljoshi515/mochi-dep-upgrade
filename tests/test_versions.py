"""The verifier's PEP 440 / PEP 508 reader."""

from __future__ import annotations

import pytest

from verifier.versions import admits, canonical_name, compare, parse_requirement, parse_specifier, release


def test_canonical_names():
    assert canonical_name("SQLAlchemy") == "sqlalchemy"
    assert canonical_name("pydantic_settings") == "pydantic-settings"
    assert canonical_name(" Pydantic.Settings ") == "pydantic-settings"


def test_release_tuples_and_comparison():
    assert release("2.14.1") == (2, 14, 1)
    assert release("v1.0") == (1, 0)
    assert release("2.0.0rc1") == (2, 0, 0)
    assert release("2.0.0.post1") == (2, 0, 0)
    assert release("1.26.4+local.1") == (1, 26, 4)
    assert release("nope") is None
    assert release("1.2.x") is None
    assert compare((2, 0), (2, 0, 0)) == 0
    assert compare((1, 10, 13), (2,)) == -1
    assert compare((3, 0, 6), (2, 2)) == 1


def test_specifier_parsing():
    assert parse_specifier(">=1.10.13,<2") == [(">=", "1.10.13"), ("<", "2")]
    assert parse_specifier("(>=1.10, <2)") == [(">=", "1.10"), ("<", "2")]
    assert parse_specifier("") == []
    assert parse_specifier("==2.14.*") == [("==", "2.14.*")]
    for bad in ("1.2", ">=", "~=2.*", ">=a.b", ">=1,,<2"):
        with pytest.raises(ValueError):
            parse_specifier(bad)


@pytest.mark.parametrize(
    ("specifier", "version", "expected"),
    [
        (">=1.10.13,<2", "1.10.13", True),
        (">=1.10.13,<2", "1.10.26", True),
        (">=1.10.13,<2", "2.0.0", False),
        (">=1.10.13,<2", "2.14.1", False),
        ("==2.14.1", "2.14.1", True),
        ("==2.14.1", "2.14.0", False),
        ("==2.14.1", "2.14.1.0", True),
        ("==2.14.*", "2.14.9", True),
        ("==2.14.*", "2.15.0", False),
        ("!=2.14.*", "2.14.1", False),
        ("!=2.14.1", "2.14.2", True),
        ("~=2.14.1", "2.14.5", True),
        ("~=2.14.1", "2.15.0", False),
        ("~=2.14", "2.99", True),
        ("~=2.14", "3.0", False),
        (">2", "2.0.0", False),
        (">2", "2.0.1", True),
        ("<=2.14.1", "2.14.1", True),
        ("<2.15", "2.14.1", True),
        ("===2.14.1", "2.14.1", True),
        ("===2.14.1", "2.14.1.0", False),
        (">=3.1,<4", "3.1.3", True),
        (">=2.1,<2.2", "2.1.4", True),
        (">=2.1,<2.2", "3.0.6", False),
    ],
)
def test_admits(specifier: str, version: str, expected: bool):
    assert admits(specifier, version) is expected


def test_admits_refuses_non_versions():
    assert admits(">=1", "latest") is False


def test_requirement_parsing():
    plain = parse_requirement("pydantic>=1.10.13,<2")
    assert plain.name == "pydantic" and plain.specifier == ">=1.10.13,<2" and not plain.marker and not plain.url
    extras = parse_requirement('SQLAlchemy[asyncio, mypy] (>=2.0) ; python_version >= "3.8"')
    assert extras.name == "sqlalchemy" and extras.extras == ("asyncio", "mypy")
    assert extras.specifier == ">=2.0" and extras.marker == 'python_version >= "3.8"'
    bare = parse_requirement("pytest")
    assert bare.specifier == "" and bare.raw_name == "pytest"
    url = parse_requirement("pydantic @ https://example.invalid/pydantic.whl")
    assert url.url.startswith("https://") and url.specifier == ""
    assert parse_requirement("Flask == 3.1.3").specifier == "==3.1.3"
    for bad in ("", ">=1.0", "pydantic>=", "pydantic[email", "pydantic >= one"):
        with pytest.raises(ValueError):
            parse_requirement(bad)
