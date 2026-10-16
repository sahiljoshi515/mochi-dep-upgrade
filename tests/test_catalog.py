"""The shipped catalog: every entry is complete and consistent with its locks, the contract's enum
names exactly its instances, and its rules are ones the verifier can apply."""

from __future__ import annotations

import re

import pytest

from contract import InstanceId
from verifier import catalog
from verifier.checks import is_sha
from verifier.locks import read_lock
from verifier.specs import KINDS
from verifier.trees import glob_regex
from verifier.versions import admits, canonical_name, parse_requirement

ENTRIES = catalog.load()["instances"]


def test_the_enum_is_the_catalog():
    assert sorted(member.value for member in InstanceId) == sorted(item["id"] for item in ENTRIES)


@pytest.mark.parametrize("item", ENTRIES, ids=lambda item: item["id"])
def test_entry_is_consistent(item: dict):
    dep = canonical_name(item["dependency"])
    base, gold = read_lock(catalog.lock_text(item, "base")), read_lock(catalog.lock_text(item, "gold"))
    assert {pin["version"] for pin in base[dep]} == {item["from_version"]}
    assert {pin["version"] for pin in gold[dep]} == {item["target_version"]}
    gold_hashes = {sha for pin in gold[dep] for sha in pin["hashes"]}
    assert gold_hashes <= {file["sha256"] for file in item["target_files"]}
    assert item["spec"]["kind"] in KINDS
    upstream = parse_requirement(item["spec"]["upstream_requirement"])
    assert admits(upstream.specifier, item["target_version"])
    assert item["spec"]["must_exclude_old"] == (not admits(upstream.specifier, item["from_version"]))
    assert is_sha(item["base"]["tree_sha256"]) and re.fullmatch(r"[0-9a-f]{40}", item["base"]["commit"])
    assert item["public"]["ids"] and item["hidden"]["ids"]
    assert len(item["public"]["excluded"]) <= 0.2 * (len(item["public"]["ids"]) + len(item["public"]["excluded"]))
    assert set(item["hidden"]["targets"]) <= set(item["hidden"]["files"])
    assert all(test.split("::")[0] in item["hidden"]["targets"] for test in item["hidden"]["ids"])
    assert all(is_sha(sha) for sha in item["hidden"]["files"].values())
    assert item["breakage"]["public"] + item["breakage"]["hidden"] > 0
    for pattern in item["forbidden"]:
        re.compile(pattern)
    editable = [item["spec"]["file"], *item["source_globs"]]
    assert all(any(glob_regex(glob).fullmatch(rel) for glob in editable) for rel in item["gold"]["files"])
    assert not any(glob_regex(glob).fullmatch(test.split("::")[0]) for glob in item["source_globs"] for test in item["public"]["ids"])
    assert item["fit"] in ("hosted", "local")
