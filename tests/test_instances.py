"""The oracle over every shipped project (needs PyPI): pristine passes its public tests on the old
version and fails the hidden ones; the pristine code fails on the target; the solution passes
everything with exactly the target locked."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from plugin.instances import all_instances
from plugin.tools_dev.check_instances import check

NETWORK = pytest.mark.skipif(not os.environ.get("NANOAGENT_NETWORK"), reason="needs PyPI; set NANOAGENT_NETWORK=1")


@NETWORK
@pytest.mark.network
@pytest.mark.parametrize("inst", all_instances(), ids=lambda inst: inst.id)
def test_instance_oracle(inst):
    with tempfile.TemporaryDirectory(prefix=f"dep-upgrade-oracle-{inst.id}-") as scratch:
        problems = check(inst, Path(scratch).resolve(), write_ids=False)
    assert problems == []
