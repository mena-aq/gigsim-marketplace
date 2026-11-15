"""Read-only authenticated Streamable HTTP smoke checks; no external sends."""

import asyncio
import os
import uuid

import httpx
from dotenv import dotenv_values
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from agent.marketplace_port import MCPMarketplacePort
from agent.mcp_client import MCPGateway


async def main() -> None:
    environment = {**dotenv_values(".env"), **os.environ}
    token = environment.get("MCP_TOKEN_ML_ENGINEER")
    if not token:
        raise SystemExit("Set MCP_TOKEN_ML_ENGINEER and run make mcp-bootstrap first")
    for name, port in (("portfolio", 8101), ("marketplace", 8102), ("workspace", 8103)):
        url = environment.get(f"{name.upper()}_MCP_URL", f"http://localhost:{port}/mcp")
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Trace-ID": "smoke-" + str(uuid.uuid4()),
        }
        async with (
            httpx.AsyncClient(headers=headers) as http,
            streamable_http_client(url, http_client=http) as streams,
            ClientSession(streams[0], streams[1]) as session,
        ):
            await session.initialize()
            tools = await session.list_tools()
            tool = {
                "portfolio": "list_skills",
                "marketplace": "get_connects_balance",
                "workspace": "get_free_slots",
            }[name]
            result = await session.call_tool(tool, {})
            if result.isError or not result.structuredContent["ok"]:
                raise RuntimeError(f"{name} tool failed")
            print(
                f"{name}: authenticated HTTP call passed; {len(tools.tools)} tools discovered"
            )
    urls = {
        name: environment.get(f"{name.upper()}_MCP_URL", f"http://localhost:{port}/mcp")
        for name, port in (
            ("portfolio", 8101),
            ("marketplace", 8102),
            ("workspace", 8103),
        )
    }
    gateway = MCPGateway(token, "scout", str(uuid.uuid4()), urls=urls)
    tools = await gateway.tools()
    if {tool.name for tool in tools} != {"search_jobs", "get_connects_balance"}:
        raise RuntimeError("Scout tool allowlist failed")
    await MCPMarketplacePort(gateway).get_connects_balance()
    print("MCP-only typed marketplace port and Scout allowlist passed")


if __name__ == "__main__":
    asyncio.run(main())
