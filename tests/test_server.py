"""The MCP server end to end over stdio: its tool schemas are the contract's, and a call works."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from slimconfig import output_schema

from contract import TOOLS

ROOT = Path(__file__).resolve().parents[1]


def test_the_server_offers_the_contract_and_answers_calls(tmp_path: Path) -> None:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "plugin"], cwd=str(ROOT), env={**os.environ, "NANOAGENT_WORKSPACE": str(tmp_path)}
    )

    async def run() -> None:
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            offered = {tool.name: tool for tool in (await session.list_tools()).tools}
            assert set(offered) == {tool.value for tool in TOOLS}
            for tool, (given, made) in TOOLS.items():
                assert offered[tool.value].inputSchema == output_schema(given)
                assert offered[tool.value].outputSchema == output_schema(made)
            result = await session.call_tool("unpack_inbox", {"seed": 5, "size": "small"})
            assert not result.isError
            payload = result.structuredContent or json.loads(result.content[0].text)
            assert payload["root"] == "file-organizer/5-small" and payload["files"] == 60 and "## 1. Delete" in payload["rules"]
            page = await session.call_tool("inventory", {"root": "file-organizer/5-small", "offset": 0, "limit": 100})
            assert not page.isError
            rows = (page.structuredContent or json.loads(page.content[0].text))["files"]
            assert len(rows) == 60 and all(len(row["sha256"]) == 64 for row in rows)
            assert [row["i"] for row in rows] == list(range(60))
            failure = await session.call_tool("inventory", {"root": "file-organizer/9-small", "offset": 0, "limit": 100})
            assert failure.isError and "unpack_inbox" in failure.content[0].text
            rules = await session.call_tool("read_rules", {})
            assert not rules.isError

    anyio.run(run)
