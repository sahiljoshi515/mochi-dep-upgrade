"""The MCP server as NanoAgent starts it: it offers exactly the contract's tools with the contract's
schemas, and refuses a call it cannot take with a plain message."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from slimconfig import output_schema

from contract import TOOLS, Tool

ROOT = Path(__file__).resolve().parents[1]


async def with_server(workspace: Path, body):
    env = {**os.environ, "NANOAGENT_WORKSPACE": str(workspace)}
    params = StdioServerParameters(command="uv", args=["run", "--frozen", "python", "-m", "plugin"], cwd=str(ROOT), env=env)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        return await body(session)


def test_offered_schemas_match_the_contract(tmp_path: Path):
    async def body(session: ClientSession):
        return {tool.name: (tool.inputSchema, tool.outputSchema) for tool in (await session.list_tools()).tools}

    offered = asyncio.run(with_server(tmp_path, body))
    assert set(offered) == {tool.value for tool in Tool}
    for tool, (given, made) in TOOLS.items():
        assert offered[tool.value] == (output_schema(given), output_schema(made))


def test_a_tool_before_start_is_refused_plainly(tmp_path: Path):
    async def body(session: ClientSession):
        return await session.call_tool("sync", arguments={"instance": "respx-httpx-0.28"})

    result = asyncio.run(with_server(tmp_path, body))
    assert result.isError
    text = " ".join(getattr(item, "text", "") for item in result.content)
    assert "start_upgrade respx-httpx-0.28 first" in text and str(tmp_path) not in text
