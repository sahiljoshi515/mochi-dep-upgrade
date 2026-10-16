"""Reading a hashed requirements lock as ``uv pip compile --universal --generate-hashes`` writes it:

    name==version ; marker \\
        --hash=sha256:<64 hex> \\
        --hash=sha256:<64 hex>

``read_lock(text)`` returns every pinned package: canonical name -> list of ``{version, marker,
hashes}`` (a universal lock may pin one name twice under different markers). Anything else on a
requirement line (a URL, an editable, an option other than --hash) makes it unreadable.
"""

import re

from .versions import canonical_name

PIN = re.compile(r"^([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)(\[[^\]]*\])?==([A-Za-z0-9.+!_-]+)$")
HASH = re.compile(r"^--hash=sha256:([0-9a-f]{64})$")


def logical_lines(text):
    """The lock's lines with backslash continuations joined and comments dropped."""
    joined = []
    current = ""
    for raw in text.splitlines():
        line = raw.split(" #", 1)[0] if not raw.lstrip().startswith("--hash") else raw
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.endswith("\\"):
            current += stripped[:-1].strip() + " "
            continue
        current += stripped
        if current.strip():
            joined.append(current.strip())
        current = ""
    if current.strip():
        joined.append(current.strip())
    return joined


def read_lock(text):
    """canonical name -> [{"version", "marker", "hashes"}], in lock order; raises ValueError."""
    packages = {}
    for line in logical_lines(text):
        words = line.split()
        hashes = []
        head = []
        for word in words:
            if word.startswith("--"):
                found = HASH.match(word)
                if not found:
                    raise ValueError(f"the lock holds an option that is not a sha256 hash: {word[:40]!r}")
                hashes.append(found.group(1))
            else:
                if hashes:
                    raise ValueError(f"the lock holds text after a hash: {line[:60]!r}")
                head.append(word)
        requirement = " ".join(head)
        pin, _, marker = requirement.partition(";")
        found = PIN.match(pin.strip())
        if not found:
            raise ValueError(f"the lock holds a line that is not name==version: {requirement[:60]!r}")
        if not hashes:
            raise ValueError(f"the lock pins {found.group(1)} without a hash")
        name = canonical_name(found.group(1))
        packages.setdefault(name, []).append({"version": found.group(3), "marker": marker.strip(), "hashes": sorted(set(hashes))})
    return packages


def versions_of(packages):
    """canonical name -> sorted versions pinned for it."""
    return {name: sorted({entry["version"] for entry in entries}) for name, entries in packages.items()}
