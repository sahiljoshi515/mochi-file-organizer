"""The MCP server over stdio, as NanoAgent speaks to it: schemas, a survey and an apply, an error."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from messy import messy, unpack
from slimconfig import output_schema

from contract import TOOLS

ROOT = Path(__file__).resolve().parents[1]


async def talk(workspace: Path, script):
    params = StdioServerParameters(command=sys.executable, args=["-m", "plugin"], cwd=str(ROOT), env={**os.environ, "NANOAGENT_WORKSPACE": str(workspace)})
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        return await script(session)


def test_the_server_offers_the_contract_and_runs_a_folder(tmp_path: Path) -> None:
    unpack(messy(1, "small", "Downloads"), tmp_path)

    async def script(session):
        offered = {tool.name: tool for tool in (await session.list_tools()).tools}
        assert set(offered) == {tool.value for tool in TOOLS}
        for tool, (given, made) in TOOLS.items():
            assert offered[tool.value].inputSchema == output_schema(given)
            assert offered[tool.value].outputSchema == output_schema(made)
        early = await session.call_tool("apply", {"folder": "Downloads", "moves": [], "deletes": []})
        assert early.isError and "call survey" in early.content[0].text
        survey = await session.call_tool("survey", {"folder": "Downloads"})
        assert not survey.isError
        rows = survey.structuredContent["rows"]
        assert rows and all(set(row) == {"i", "path", "h", "base", "drop"} for row in rows)
        junk = next(row for row in rows if row["drop"])
        applied = await session.call_tool("apply", {"folder": "Downloads", "moves": [], "deletes": [junk["i"]]})
        assert not applied.isError and applied.structuredContent["applied"] == 1
        missing = await session.call_tool("pin_layout", {"folder": "Nope"})
        assert missing.isError and "No folder Nope" in missing.content[0].text
        assert str(tmp_path) not in survey.content[0].text  # no workspace paths in outputs

    anyio.run(talk, tmp_path, script)
