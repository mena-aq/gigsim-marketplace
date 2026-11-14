"""MCP-only agent access with role allowlists and per-run trace propagation."""

import os
from collections.abc import Mapping
from typing import Any

import httpx
from langchain_mcp_adapters.client import MultiServerMCPClient
from mcp.shared.exceptions import McpError

from mcp_servers.common.errors import ToolFailure

AGENT_TOOLS = {
    "scout": {"search_jobs", "get_job", "get_connects_balance"},
    "analyst": set(),
    "risk": {"get_client_history", "get_job"},
    "matcher": {"search_evidence", "get_case_study", "list_skills"},
    "pricing": {"search_jobs", "get_connects_balance", "get_client_history"},
    "writer": {"search_evidence", "get_case_study"},
    "critic": {"search_evidence", "get_case_study", "verify_claims"},
    "verifier": {"verify_claims"},
    # R&D question C baseline: one agent holding every read-only tool, no write tools.
    "single_agent": {
        "get_job",
        "get_client_history",
        "search_evidence",
        "get_case_study",
        "list_skills",
    },
    "compliance": set(),
    "liaison": {
        "list_conversations",
        "list_messages",
        "get_free_slots",
        "create_hold",
        "create_email_draft",
        "send_message",
    },
    "approval_executor": {"submit_proposal", "send_message", "create_proposal_draft"},
}
SERVER_TOOLS = {
    "portfolio": {"search_evidence", "get_case_study", "list_skills", "verify_claims"},
    "marketplace": {
        "search_jobs",
        "get_job",
        "get_client_history",
        "get_connects_balance",
        "list_conversations",
        "list_messages",
        "create_proposal_draft",
        "submit_proposal",
        "send_message",
    },
    "workspace": {"get_free_slots", "create_hold", "create_email_draft"},
}


class MCPGateway:
    def __init__(
        self,
        token: str,
        role: str,
        trace_id: str,
        urls: Mapping[str, str] | None = None,
    ):
        if role not in AGENT_TOOLS:
            raise ValueError("Unknown agent role")
        self.allowed = AGENT_TOOLS[role]
        urls = urls or {
            name: os.environ.get(
                f"{name.upper()}_MCP_URL", f"http://localhost:{port}/mcp"
            )
            for name, port in (
                ("portfolio", 8101),
                ("marketplace", 8102),
                ("workspace", 8103),
            )
        }
        self.client = MultiServerMCPClient(
            {
                name: {
                    "transport": "streamable_http",
                    "url": url,
                    "headers": {
                        "Authorization": f"Bearer {token}",
                        "X-Trace-ID": trace_id,
                    },
                    "timeout": float(os.environ.get("MCP_CALL_TIMEOUT_SECONDS", "600")),
                }
                for name, url in urls.items()
            }
        )

    async def tools(self) -> list:
        tools = []
        for server, names in SERVER_TOOLS.items():
            if self.allowed & names:
                try:
                    tools.extend(
                        tool
                        for tool in await self.client.get_tools(server_name=server)
                        if tool.name in self.allowed
                    )
                except (httpx.HTTPError, McpError, OSError, ExceptionGroup):
                    raise ToolFailure(
                        "mcp_unavailable", f"{server} MCP is unavailable", True
                    ) from None
        return tools

    async def call(self, tool: str, arguments: dict[str, Any]) -> dict:
        if tool not in self.allowed:
            raise ToolFailure("forbidden_tool", "This role cannot use that tool")
        server = next(name for name, tools in SERVER_TOOLS.items() if tool in tools)
        try:
            async with self.client.session(server) as session:
                response = await session.call_tool(tool, arguments)
        except (httpx.HTTPError, McpError, OSError, ExceptionGroup):
            raise ToolFailure(
                "mcp_unavailable", f"{server} MCP is unavailable", True
            ) from None
        if response.isError or response.structuredContent is None:
            raise ToolFailure(
                "invalid_tool_result", "MCP tool returned an invalid result"
            )
        result = response.structuredContent
        if not result["ok"]:
            failure = result["error"]
            raise ToolFailure(
                failure["code"],
                failure["message"],
                failure["retryable"],
                failure["retry_after"],
            )
        return result["data"]
