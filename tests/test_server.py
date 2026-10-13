"""The MCP server end to end: the offered schemas are the contract's; with the network, a gold
upgrade of one project through the tools ends in a valid verdict and a shim in an invalid one."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent
from slimconfig import build_output, output_schema

import verifier
from contract import TOOLS, PinOutput, Tool, UpgradeInput
from plugin.common import oversized, scratch_home
from plugin.instances import load_instance
from plugin.tools_dev.patches import changed_files_of

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "arrays-numpy-2"
NETWORK = pytest.mark.skipif(not os.environ.get("NANOAGENT_NETWORK"), reason="needs PyPI; set NANOAGENT_NETWORK=1")


async def with_server(workspace: Path, body):
    env = {**os.environ, "NANOAGENT_WORKSPACE": str(workspace)}
    env.pop("UV_OFFLINE", None)
    env.pop("UV_NO_SYNC", None)
    params = StdioServerParameters(command="uv", args=["run", "--frozen", "python", "-m", "plugin"], cwd=str(ROOT), env=env)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        return await body(session)


def call(session: ClientSession, tool: str, arguments: dict):
    async def run():
        result = await session.call_tool(tool, arguments=arguments)
        if result.isError:
            raise RuntimeError(" ".join(item.text for item in result.content if isinstance(item, TextContent)))
        if result.structuredContent is not None:
            return result.structuredContent
        return json.loads(next(item.text for item in result.content if isinstance(item, TextContent)))

    return run()


def test_offered_schemas_match_the_contract(tmp_path: Path):
    async def body(session: ClientSession):
        return {tool.name: (tool.inputSchema, tool.outputSchema) for tool in (await session.list_tools()).tools}

    offered = asyncio.run(with_server(tmp_path, body))
    assert set(offered) == {tool.value for tool in Tool}
    for tool, (given, made) in TOOLS.items():
        assert offered[tool.value] == (output_schema(given), output_schema(made))


def test_tools_refuse_before_start(tmp_path: Path):
    async def body(session: ClientSession):
        with pytest.raises(RuntimeError, match="start_project"):
            await call(session, "write_file", {"files": [{"path": f"dep-upgrade/{PROJECT}/pyproject.toml", "content": "x"}]})
        with pytest.raises(RuntimeError, match="start_project"):
            await call(session, "sync", {"project": PROJECT})
        return await call(session, "pin_project", {"project": PROJECT})

    pin = asyncio.run(with_server(tmp_path, body))
    assert pin["target_version"] == load_instance(PROJECT).target_version


@NETWORK
@pytest.mark.network
def test_gold_upgrade_through_the_tools_is_valid(tmp_path: Path):
    inst = load_instance(PROJECT)
    files = changed_files_of(inst)

    async def body(session: ClientSession):
        pin = await call(session, "pin_project", {"project": PROJECT})
        started = await call(session, "start_project", {"project": PROJECT})
        assert started["current_version"] == inst.from_version
        assert started["complete"] is True and started["uses_dependency"]
        items = [{"path": f"dep-upgrade/{PROJECT}/{rel}", "content": content} for rel, content in sorted(files.items())]
        for start in range(0, len(items), 5):
            written = await call(session, "write_file", {"files": items[start : start + 5]})
            assert [item["path"] for item in written["written"]] == [item["path"] for item in items[start : start + 5]]
        synced = await call(session, "sync", {"project": PROJECT})
        assert synced["ok"] is True and synced["complete"] is True and synced["installed"][inst.dependency] == inst.target_version
        built = await call(session, "run_build", {"project": PROJECT})
        assert built["ok"] is True and built["wheel"].endswith(".whl")
        tests = await call(session, "run_tests", {"project": PROJECT, "tests": []})
        assert tests["exit_code"] == 0 and tests["failed"] == 0
        judged = await call(session, "judge", {"project": PROJECT})
        assert judged["recorded"] is True and judged["complete"] is True and judged["build_ok"] is True and judged["public_failed"] == 0
        return pin

    pin = asyncio.run(with_server(tmp_path, body))
    found = verifier.verify_task("upgrade-dependency", build_output({"project": PROJECT}, UpgradeInput), build_output(pin, PinOutput), str(tmp_path))
    assert found["valid"] is True and found["score"] == 1.0, found
    # Nothing heavy in the workspace: the venv, wheels and run folders live in the scratch home.
    root = tmp_path / "dep-upgrade" / PROJECT
    assert sorted(path.name for path in root.iterdir()) == [".git", ".judge", "README.md", "pyproject.toml", "src", "tests", "uv.lock"]
    assert sorted(path.name for path in (root / ".judge").iterdir()) == ["diff.patch", "judgement.json", "progress.json", "ready.json"]
    assert oversized(tmp_path) == []
    assert (scratch_home(tmp_path) / PROJECT / ".venv" / "bin" / "python").exists()


@NETWORK
@pytest.mark.network
def test_bump_without_sync_is_invalid(tmp_path: Path):
    inst = load_instance(PROJECT)
    files = changed_files_of(inst)

    async def body(session: ClientSession):
        pin = await call(session, "pin_project", {"project": PROJECT})
        await call(session, "start_project", {"project": PROJECT})
        await call(session, "write_file", {"files": [{"path": f"dep-upgrade/{PROJECT}/pyproject.toml", "content": files["pyproject.toml"]}]})
        judged = await call(session, "judge", {"project": PROJECT})
        assert judged["lock_ok"] is False
        return pin

    pin = asyncio.run(with_server(tmp_path, body))
    found = verifier.verify_task("upgrade-dependency", build_output({"project": PROJECT}, UpgradeInput), build_output(pin, PinOutput), str(tmp_path))
    assert found["valid"] is False and found["score"] == 0.0
    assert any("uv.lock holds numpy 1.26.4" in item for item in found["details"]["violations"])
    shutil.rmtree(tmp_path / "dep-upgrade", ignore_errors=True)


def test_python_is_the_plugins(tmp_path: Path):
    assert sys.version_info[:2] == (3, 12)
