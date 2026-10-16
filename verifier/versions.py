"""Versions, specifiers and requirements: the small part of PEP 440 and PEP 508 an upgrade writes.

Versions compare by their release segment (``2.14.1``); a pre-, post- or dev suffix is read but
does not order (every version this plugin pins is a final release). Operators: ``==`` (also
``==2.*``), ``!=``, ``>=``, ``>``, ``<=``, ``<``, ``~=`` and ``===``.
"""

import re
from dataclasses import dataclass

RELEASE = re.compile(r"^v?(\d+(?:\.\d+)*)(.*)$")
OPERATOR = re.compile(r"^(===|==|!=|<=|>=|~=|<|>)\s*(.+?)\s*$")
NAME = re.compile(r"^([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)")
OPERATORS = ("===", "==", "!=", "<=", ">=", "~=", "<", ">")


def canonical_name(name):
    """A distribution name as PEP 503 normalizes it: ``SQLAlchemy`` and ``sqlalchemy`` are one."""
    return re.sub(r"[-_.]+", "-", name.strip()).lower()


def release(version):
    """The release tuple of ``version`` (``"2.14.1"`` -> ``(2, 14, 1)``), or None if it is not a version."""
    found = RELEASE.match(version.strip())
    if not found:
        return None
    suffix = found.group(2)
    if suffix and not re.fullmatch(r"(?:[-._]?(?:a|b|c|rc|alpha|beta|pre|preview|post|rev|r|dev)\.?\d*)*(?:\+[A-Za-z0-9.]+)?", suffix, re.IGNORECASE):
        return None
    return tuple(int(part) for part in found.group(1).split("."))


def compare(left, right):
    """-1, 0 or 1 for two release tuples, shorter one padded with zeros (``2.0`` equals ``2.0.0``)."""
    size = max(len(left), len(right))
    first = left + (0,) * (size - len(left))
    second = right + (0,) * (size - len(right))
    return (first > second) - (first < second)


def parse_specifier(text):
    """``">=1.10,<2"`` -> ``[(">=", "1.10"), ("<", "2")]``; raises ValueError for anything else."""
    text = text.strip()
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    if not text:
        return []
    parts = []
    for piece in text.split(","):
        piece = piece.strip()
        if not piece:
            raise ValueError("empty version clause")
        found = OPERATOR.match(piece)
        if not found:
            raise ValueError(f"not a version clause: {piece!r}")
        operator, version = found.group(1), found.group(2)
        if operator == "===":
            parts.append((operator, version))
            continue
        wildcard = version.endswith(".*")
        if wildcard and operator not in ("==", "!="):
            raise ValueError(f"a wildcard needs == or !=: {piece!r}")
        if release(version[:-2] if wildcard else version) is None:
            raise ValueError(f"not a version: {version!r}")
        parts.append((operator, version))
    return parts


def _prefix_match(version, prefix):
    """Whether ``version``'s release starts with ``prefix``'s release (``==2.14.*``)."""
    have, want = release(version), release(prefix)
    return have is not None and want is not None and have[: len(want)] + (0,) * max(0, len(want) - len(have)) == want


def admits(specifier, version):
    """Whether every clause of ``specifier`` (text or parsed) holds for ``version``."""
    clauses = parse_specifier(specifier) if isinstance(specifier, str) else specifier
    have = release(version)
    if have is None:
        return False
    for operator, wanted in clauses:
        if operator == "===":
            if version.strip() != wanted:
                return False
            continue
        if wanted.endswith(".*"):
            matched = _prefix_match(version, wanted[:-2])
            if (operator == "==" and not matched) or (operator == "!=" and matched):
                return False
            continue
        want = release(wanted)
        order = compare(have, want)
        if operator == "==" and order != 0:
            return False
        if operator == "!=" and order == 0:
            return False
        if operator == ">=" and order < 0:
            return False
        if operator == ">" and order <= 0:
            return False
        if operator == "<=" and order > 0:
            return False
        if operator == "<" and order >= 0:
            return False
        if operator == "~=":
            if order < 0:
                return False
            if len(want) >= 2 and not _prefix_match(version, ".".join(str(part) for part in want[:-1])):
                return False
    return True


@dataclass(frozen=True)
class Requirement:
    name: str  # canonical
    raw_name: str
    extras: tuple
    specifier: str  # normalized clauses, comma-joined, no spaces
    marker: str
    url: str
    text: str


def parse_requirement(text):
    """Read one PEP 508 requirement; raises ValueError when it is not one this plugin accepts."""
    original = text
    body, _, marker = text.partition(";")
    body = body.strip()
    found = NAME.match(body)
    if not found:
        raise ValueError(f"not a requirement: {original!r}")
    raw_name = found.group(1)
    rest = body[found.end() :].strip()
    extras = ()
    if rest.startswith("["):
        close = rest.find("]")
        if close < 0:
            raise ValueError(f"unclosed extras: {original!r}")
        extras = tuple(sorted(part.strip() for part in rest[1:close].split(",") if part.strip()))
        rest = rest[close + 1 :].strip()
    url = ""
    if rest.startswith("@"):
        url = rest[1:].strip()
        rest = ""
    clauses = parse_specifier(rest)
    specifier = ",".join(f"{operator}{version}" for operator, version in clauses)
    return Requirement(
        name=canonical_name(raw_name),
        raw_name=raw_name,
        extras=extras,
        specifier=specifier,
        marker=marker.strip(),
        url=url,
        text=original.strip(),
    )


def requirement_key(text):
    """A requirement as a comparable key: canonical name, sorted extras, its clauses as a sorted
    tuple, its marker with spacing and quotes normalized, its URL. Two spellings of one
    requirement (``a>=1,<2`` and ``A <2, >=1``) give the same key."""
    requirement = parse_requirement(text)
    clauses = tuple(sorted(clause for clause in requirement.specifier.split(",") if clause))
    marker = re.sub(r"\s+", "", requirement.marker).replace("'", '"')
    return (requirement.name, requirement.extras, clauses, marker, requirement.url)
