"""Workspace MCP: local-only free slots, tentative holds, and email drafts."""

from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import Field

from mcp_servers.common.runtime import Runtime
from mcp_servers.common.schemas import (
    EmailRequest,
    FreeSlots,
    HoldRequest,
    Result,
    WriteResult,
)
from mcp_servers.common.server import http_app, make_server
from mcp_servers.workspace.service import WorkspaceService

READ = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)
WRITE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
)


def create_server(runtime: Runtime):
    server = make_server("GigBid Workspace", runtime)
    service = WorkspaceService(runtime)

    @server.tool(annotations=READ)
    async def get_free_slots(
        days_ahead: Annotated[int, Field(ge=1, le=30)] = 7,
    ) -> Result[FreeSlots]:
        """List available one-hour weekday slots, 09:00–17:00 Asia/Karachi, excluding your local holds."""
        return await runtime.run(
            "get_free_slots",
            {"days_ahead": days_ahead},
            lambda who: service.free_slots(who, days_ahead),
        )

    @server.tool(annotations=WRITE)
    async def create_hold(request: HoldRequest) -> Result[WriteResult]:
        """Preview or save a tentative local interview hold. Never creates an external calendar event."""
        return await runtime.run(
            "create_hold",
            request.model_dump(mode="json"),
            lambda who: service.hold(who, request),
        )

    @server.tool(annotations=WRITE)
    async def create_email_draft(request: EmailRequest) -> Result[WriteResult]:
        """Preview or save a local email draft. Never sends email or contacts a provider."""
        return await runtime.run(
            "create_email_draft",
            request.model_dump(mode="json"),
            lambda who: service.email(who, request),
        )

    return server


def create_app():
    runtime = Runtime()
    return http_app(create_server(runtime), runtime)
