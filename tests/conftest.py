"""Shared fixtures: network tests are skipped unless NANOAGENT_NETWORK is set; ``demo`` points the
verifier and the tools at a synthetic catalog for the duration of a test."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import synthetic

from verifier import catalog


def pytest_collection_modifyitems(config, items):
    if os.environ.get("NANOAGENT_NETWORK"):
        return
    skip = pytest.mark.skip(reason="needs GitHub and PyPI; set NANOAGENT_NETWORK=1 to run")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def demo(tmp_path: Path):
    """The synthetic instance's catalog entry; the verifier reads the synthetic catalog meanwhile."""
    saved = (catalog.DATA, catalog.CATALOG)
    project = tmp_path / "project"
    synthetic.write_project(project, synthetic.FILES)
    item = synthetic.install_catalog(tmp_path / "data", project)
    yield item
    catalog.DATA, catalog.CATALOG = saved
    catalog.load.cache_clear()
