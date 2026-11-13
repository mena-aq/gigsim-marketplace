"""Intentional MCP contract changes require reviewing the committed snapshot."""

import json
from pathlib import Path

from mcp_servers.common.config import MCPSettings
from mcp_servers.common.runtime import Runtime
from mcp_servers.marketplace.server import create_server as marketplace
from mcp_servers.portfolio.server import create_server as portfolio
from mcp_servers.workspace.server import create_server as workspace


async def test_mcp_schema_snapshot():
    runtime = Runtime(MCPSettings(_env_file=None, database_url="sqlite+aiosqlite://"))
    try:
        actual = {}
        for name, factory in (
            ("portfolio", portfolio),
            ("marketplace", marketplace),
            ("workspace", workspace),
        ):
            server = factory(runtime)
            actual[name] = [
                tool.model_dump(mode="json", exclude_none=True)
                for tool in await server.list_tools()
            ]
        expected = json.loads((Path(__file__).parent / "mcp_schemas.json").read_text())
        assert actual == expected
    finally:
        await runtime.close()
