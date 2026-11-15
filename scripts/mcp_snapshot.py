"""Explicitly regenerate MCP schema snapshots; review the diff before committing."""

import asyncio
import json
from pathlib import Path

from mcp_servers.common.config import MCPSettings
from mcp_servers.common.runtime import Runtime
from mcp_servers.marketplace.server import create_server as marketplace
from mcp_servers.portfolio.server import create_server as portfolio
from mcp_servers.workspace.server import create_server as workspace


async def main() -> None:
    runtime = Runtime(MCPSettings(_env_file=None, database_url="sqlite+aiosqlite://"))
    try:
        data = {}
        for name, factory in (
            ("portfolio", portfolio),
            ("marketplace", marketplace),
            ("workspace", workspace),
        ):
            data[name] = [
                tool.model_dump(mode="json", exclude_none=True)
                for tool in await factory(runtime).list_tools()
            ]
        path = Path(__file__).resolve().parents[1] / "tests/contract/mcp_schemas.json"
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    finally:
        await runtime.close()


if __name__ == "__main__":
    asyncio.run(main())
