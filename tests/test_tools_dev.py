"""The build tools that make gold cases: upstream's change as exact replacements must reproduce
upstream's file, with every old text unique where it applies."""

from __future__ import annotations

import pytest

from plugin.tools_dev.cases import make_edits


def apply(before: str, edits: list[dict]) -> str:
    text = before
    for edit in edits:
        assert text.count(edit["old"]) == 1, edit
        text = text.replace(edit["old"], edit["new"], 1)
    return text


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("a\nb\nc\n", "a\nB\nc\n"),
        ("a\nb\nc\n", "new\na\nb\nc\n"),
        ("a\nb\nc\n", "a\nb\nc\nnew\n"),
        ("x = 1\nx = 1\ny = 2\n", "x = 1\nx = 2\ny = 2\n"),
        ("def f():\n    return 1\n\n\ndef g():\n    return 1\n", "def f():\n    return 2\n\n\ndef g():\n    return 1\n"),
        ("one\ntwo\nthree\nfour\n", "one\nthree\nfour\nfive\n"),
        ("keep\n" * 5 + "change\n" + "keep\n" * 5, "keep\n" * 5 + "changed\n" + "keep\n" * 5),
    ],
)
def test_make_edits_reproduces_upstream(before: str, after: str):
    assert apply(before, make_edits("x.py", before, after)) == after


def test_identical_files_need_no_edit():
    assert make_edits("x.py", "a\n", "a\n") == []
