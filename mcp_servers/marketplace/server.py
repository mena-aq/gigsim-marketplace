"""GigSim Marketplace MCP: authenticated reads, local drafts, and gated sends."""

from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import Field

from mcp_servers.common.runtime import Runtime
from mcp_servers.common.schemas import (
    ClientHistory,
    ConnectsOut,
    ConversationOut,
    JobOut,
    JobPage,
    MessageOut,
    MessageRequest,
    ProposalRequest,
    Result,
    SearchJobs,
    WriteResult,
)
from mcp_servers.common.server import http_app, make_server
from mcp_servers.marketplace.service import MarketplaceService

READ = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True
)
WRITE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True
)
SEND = ToolAnnotations(
    readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True
)
Identifier = Annotated[
    str, Field(min_length=1, max_length=140, pattern=r"^[A-Za-z0-9_:.-]+$")
]


def create_server(runtime: Runtime):
    server = make_server("GigBid Marketplace", runtime)
    service = MarketplaceService(runtime)

    @server.tool(annotations=READ)
    async def search_jobs(request: SearchJobs) -> Result[JobPage]:
        """Search open GigSim jobs with query, category, budget filters, and pagination."""
        return await runtime.run(
            "search_jobs",
            request.model_dump(),
            lambda who: service.adapter.search_jobs(who, request),
        )

    @server.tool(annotations=READ)
    async def get_job(job_id: Identifier) -> Result[JobOut]:
        """Read one job's public requirements; no hidden evaluator labels are returned."""
        return await runtime.run(
            "get_job",
            {"job_id": job_id},
            lambda who: service.adapter.get_job(who, job_id),
        )

    @server.tool(annotations=READ)
    async def get_client_history(client_id: Identifier) -> Result[ClientHistory]:
        """Read a client's public spend, hiring history, and reviews."""
        return await runtime.run(
            "get_client_history",
            {"client_id": client_id},
            lambda who: service.adapter.get_client_history(who, client_id),
        )

    @server.tool(annotations=READ)
    async def get_connects_balance() -> Result[ConnectsOut]:
        """Read the authenticated freelancer's remaining Connects without spending."""
        return await runtime.run(
            "get_connects_balance", {}, service.adapter.get_connects_balance
        )

    @server.tool(annotations=READ)
    async def list_conversations() -> Result[list[ConversationOut]]:
        """List the authenticated freelancer's conversations about submitted proposals."""
        return await runtime.run(
            "list_conversations", {}, service.adapter.list_conversations
        )

    @server.tool(annotations=READ)
    async def list_messages(conversation_id: Identifier) -> Result[list[MessageOut]]:
        """Read messages in a conversation owned by the authenticated freelancer."""
        return await runtime.run(
            "list_messages",
            {"conversation_id": conversation_id},
            lambda who: service.adapter.list_messages(who, conversation_id),
        )

    @server.tool(annotations=WRITE)
    async def create_proposal_draft(request: ProposalRequest) -> Result[WriteResult]:
        """Save a local proposal draft, or preview it with dry_run; never submits or spends."""
        return await runtime.run(
            "create_proposal_draft",
            request.model_dump(mode="json"),
            lambda who: service.proposal(who, request, draft=True),
        )

    @server.tool(annotations=SEND)
    async def submit_proposal(request: ProposalRequest) -> Result[WriteResult]:
        """Submit only an exactly approved proposal. Preview first; approval grant and expected Connects cost are required for execution."""
        return await runtime.run(
            "submit_proposal",
            request.model_dump(mode="json"),
            lambda who: service.proposal(who, request, draft=False),
        )

    @server.tool(annotations=SEND)
    async def send_message(request: MessageRequest) -> Result[WriteResult]:
        """Preview or send an exactly approved reply in your own conversation; retries use the same idempotency key."""
        return await runtime.run(
            "send_message",
            request.model_dump(mode="json"),
            lambda who: service.message(who, request),
        )

    return server


def create_app():
    runtime = Runtime()
    return http_app(create_server(runtime), runtime)
