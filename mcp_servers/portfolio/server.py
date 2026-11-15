"""Read-only Portfolio MCP with tools, resource templates, and a grounded prompt."""

import json
from pathlib import Path
from typing import Annotated
from urllib.parse import unquote

from mcp.types import ToolAnnotations
from pydantic import Field

from mcp_servers.common.runtime import Runtime
from mcp_servers.common.schemas import (
    Evidence,
    EvidencePage,
    EvidenceQuery,
    Result,
    SkillList,
    VerificationRequest,
)
from mcp_servers.common.server import http_app, make_server
from mcp_servers.portfolio.service import PortfolioService
from rag.types import VerificationReport

READ = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)


async def retired_items(runtime: Runtime, who) -> list[str]:
    from sqlalchemy import select

    from apps.api.models import RetiredEvidence

    async with runtime.sessions() as session:
        return list(
            await session.scalars(
                select(RetiredEvidence.item_id).where(
                    RetiredEvidence.user_id == who.user_id
                )
            )
        )


def create_server(runtime: Runtime):
    server = make_server("GigBid Portfolio", runtime)
    service = PortfolioService(
        runtime.settings.mcp_persona_dir,
        pipeline_factory=getattr(runtime, "rag_factory", None),
        retired_loader=lambda who: retired_items(runtime, who),
    )

    @server.tool(annotations=READ)
    async def search_evidence(request: EvidenceQuery) -> Result[EvidencePage]:
        """Retrieve owned portfolio evidence using the configured RAG variant; use returned chunk IDs for claim verification."""
        return await runtime.run(
            "search_evidence",
            request.model_dump(),
            lambda who: service.search(who, request),
        )

    @server.tool(annotations=READ)
    async def verify_claims(request: VerificationRequest) -> Result[VerificationReport]:
        """Check draft claims against owned retrieved chunks and exclude unsupported or unverified experience sentences. Never sends anything."""
        return await runtime.run(
            "verify_claims",
            request.model_dump(),
            lambda who: service.verify(who, request),
        )

    @server.tool(annotations=READ)
    async def get_case_study(
        id: Annotated[str, Field(min_length=1, max_length=250)],
    ) -> Result[Evidence]:
        """Load a full case study by an evidence ID returned by search_evidence."""
        return await runtime.run(
            "get_case_study", {"id": id}, lambda who: service.get(who, id, "case_study")
        )

    @server.tool(annotations=READ)
    async def list_skills() -> Result[SkillList]:
        """Read the explicit skills list for your assigned persona."""
        return await runtime.run("list_skills", {}, service.skills)

    @server.resource("portfolio://case/{id}")
    async def case_resource(id: str) -> str:
        """Full text and metadata of an owned case study."""
        id = unquote(id)
        return json.dumps(
            await runtime.run(
                "read_case_resource",
                {"id": id},
                lambda who: service.get(who, id, "case_study"),
            )
        )

    @server.resource("portfolio://proposal/{id}")
    async def proposal_resource(id: str) -> str:
        """Full text and metadata of an owned historical proposal."""
        id = unquote(id)
        return json.dumps(
            await runtime.run(
                "read_proposal_resource",
                {"id": id},
                lambda who: service.get(who, id, "proposal"),
            )
        )

    @server.prompt()
    async def answer_screening_question(question: str) -> str:
        """Answer a screening question using only evidence from the assigned portfolio."""
        from mcp_servers.common.security import identity

        identity()
        text = (
            Path(__file__).resolve().parents[2] / "agent/prompts/portfolio_screening.md"
        ).read_text()
        return text.replace("{question}", json.dumps(question[:4000]))

    return server


def create_app():
    runtime = Runtime()
    return http_app(create_server(runtime), runtime)
