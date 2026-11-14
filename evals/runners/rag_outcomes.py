"""Isolated, sequential GigSim experiment using real in-memory MCP sessions.

Approval grants and an unmetered quota exist only in disposable evaluation DBs.
No URL or database override is accepted for simulator writes.
"""

import random
from datetime import UTC, datetime, timedelta

import httpx
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.shared.memory import create_connected_server_and_client_session
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from apps.api.models import ApprovalGrant, Base, User
from evals.runners.rag_diagnostics import reply_diagnostics
from gigsim import reply_sim, scheduler
from gigsim.config import Settings
from gigsim.db import init_db
from gigsim.main import create_app
from gigsim.models import Client, Job, Proposal
from mcp_servers.common.config import MCPSettings
from mcp_servers.common.runtime import Runtime
from mcp_servers.common.schemas import ProposalRequest
from mcp_servers.common.security import fingerprint
from mcp_servers.marketplace.server import create_server


class EvaluationQuota:
    """Disable Redis quotas for disposable sequential evaluation fixtures only."""

    async def eval(self, *args):
        return 0

    async def aclose(self):
        return None


async def simulate_outcome(case: dict, draft: str, seed: int) -> dict:
    """Submit to a new in-memory simulator and return its persisted outcome."""
    if not draft.strip():
        return {
            "status": "empty_draft",
            "submitted": False,
            "reply": False,
            "hire": False,
        }
    settings = Settings(
        _env_file=None,
        database_url="sqlite+aiosqlite://",
        chaos_enabled=False,
        reply_delay_min_seconds=0,
        reply_delay_max_seconds=0,
    )
    app = create_app(settings)
    await init_db(app.state.engine)
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    runtime = None
    auth = None
    original_rng = reply_sim.rng
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        job = {k: v for k, v in case["job"].items() if k in Job.__table__.columns}
        job.pop("posted_at", None)
        job["status"] = "open"
        async with app.state.sessionmaker() as session:
            session.add(Client(**case["client"]))
            session.add(Job(**job))
            await session.commit()
        runtime = Runtime(
            MCPSettings(_env_file=None),
            engine=engine,
            redis=EvaluationQuota(),
            transport=httpx.ASGITransport(app=app),
        )
        async with runtime.sessions() as session:
            session.add(
                User(
                    id="evaluation",
                    email="evaluation@test.local",
                    persona=case["persona"],
                )
            )
            await session.commit()
        auth = auth_context_var.set(
            AuthenticatedUser(
                AccessToken(
                    token="isolated-evaluation",
                    subject="evaluation",
                    client_id="evaluation",
                    scopes=["gigbid"],
                    claims={"persona": case["persona"]},
                )
            )
        )
        reply_sim.rng = random.Random(seed)
        # Omit skills_mentioned: GigSim derives them from the actual cleaned text.
        request = ProposalRequest(
            job_id=job["id"], cover_letter=draft, idempotency_key="evaluation"
        )
        async with create_connected_server_and_client_session(
            create_server(runtime)
        ) as client:

            async def call(req):
                result = await client.call_tool(
                    "submit_proposal", {"request": req.model_dump()}
                )
                if result.isError or not result.structuredContent.get("ok"):
                    raise RuntimeError("Isolated Marketplace MCP submission failed")
                return result.structuredContent["data"]

            preview = await call(request.model_copy(update={"dry_run": True}))
            request.expected_connects_cost = preview["connects_cost"]
            async with runtime.sessions() as session:
                session.add(
                    ApprovalGrant(
                        user_id="evaluation",
                        tool="submit_proposal",
                        idempotency_key=request.idempotency_key,
                        payload_hash=fingerprint(
                            request.model_dump(mode="json", exclude={"dry_run"})
                        ),
                        expires_at=datetime.now(UTC) + timedelta(minutes=10),
                    )
                )
                await session.commit()
            sent = await call(request)
        await scheduler.wait_all()
        async with app.state.sessionmaker() as session:
            proposal = await session.get(Proposal, int(sent["external_id"]))
            status = proposal.status
        if status not in {"no_reply", "replied", "interview", "hired"}:
            raise RuntimeError("Simulator did not finish its reply task")
        return {
            "status": status,
            **reply_diagnostics(case, draft, status),
            "submitted": True,
            "reply": status in {"replied", "interview", "hired"},
            "hire": status == "hired",
            "connects_spent": sent["connects_cost"],
            "seed": seed,
        }
    finally:
        scheduler.cancel_all()
        reply_sim.rng = original_rng
        if auth is not None:
            auth_context_var.reset(auth)
        if runtime is not None:
            await runtime.close()
        else:
            await engine.dispose()
        await app.state.engine.dispose()
