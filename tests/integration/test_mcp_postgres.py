"""Opt-in real Postgres concurrency checks; use a disposable migrated database.

MCP audit rows and their test users intentionally persist (audit is append-only).
Simulator data lives in an isolated schema removed at teardown.
"""

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.models import ApprovalGrant, AuditLog, EmailDraft, User
from gigsim import scheduler
from gigsim.db import init_db
from gigsim.models import Proposal as SimProposal
from gigsim.tests.conftest import AUTH_ML, make_app, seed_test_data
from gigsim.tests.test_proposals import proposal_payload
from mcp_servers.common.config import MCPSettings
from mcp_servers.common.runtime import Runtime
from mcp_servers.common.schemas import EmailRequest, HoldRequest, ProposalRequest, Slot
from mcp_servers.common.security import Identity, fingerprint
from mcp_servers.marketplace.service import MarketplaceService
from mcp_servers.workspace.service import WorkspaceService

pytestmark = pytest.mark.skipif(
    not os.getenv("FOUNDATION_TEST_DATABASE_URL"),
    reason="requires disposable migrated PostgreSQL",
)


class Unlimited:
    async def eval(self, *args):
        return 0

    async def aclose(self):
        return None


@pytest.fixture
async def setup():
    url = os.environ["FOUNDATION_TEST_DATABASE_URL"]
    engine = create_async_engine(url)
    schema = "sim_" + uuid.uuid4().hex
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    simulator = make_app()
    await simulator.state.engine.dispose()
    simulator.state.engine = create_async_engine(
        url, connect_args={"server_settings": {"search_path": schema}}
    )
    simulator.state.sessionmaker = async_sessionmaker(
        simulator.state.engine, expire_on_commit=False
    )
    await init_db(simulator.state.engine)
    await seed_test_data(simulator)
    runtime = Runtime(
        MCPSettings(
            _env_file=None, database_url=url, gigsim_token_ml_engineer="test-token-ml"
        ),
        engine=engine,
        redis=Unlimited(),
        transport=httpx.ASGITransport(app=simulator),
    )
    user_id = str(uuid.uuid4())
    async with runtime.sessions() as session:
        session.add(
            User(id=user_id, email=user_id + "@example.test", persona="ml_engineer")
        )
        await session.commit()
    token = auth_context_var.set(
        AuthenticatedUser(
            AccessToken(
                token="test",
                client_id=user_id,
                subject=user_id,
                scopes=["gigbid"],
                claims={"persona": "ml_engineer"},
            )
        )
    )
    yield runtime, simulator, Identity(user_id, "ml_engineer")
    auth_context_var.reset(token)
    scheduler.cancel_all()
    await simulator.state.engine.dispose()
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    await runtime.close()


async def test_simulator_concurrent_writes_and_balance(setup):
    _runtime, app, _who = setup
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        payload = proposal_payload(idempotency_key="parallel")
        responses = await asyncio.gather(
            *(
                client.post("/proposals", json=payload, headers=AUTH_ML)
                for _ in range(8)
            )
        )
        assert all(response.status_code == 201 for response in responses)
        assert len({response.json()["id"] for response in responses}) == 1
        assert (await client.get("/connects", headers=AUTH_ML)).json()["balance"] == 52
        message = {
            "conversation_id": "job_ml:ml_engineer",
            "body": "Hello",
            "idempotency_key": "same-message",
        }
        responses = await asyncio.gather(
            *(client.post("/messages", json=message, headers=AUTH_ML) for _ in range(8))
        )
        assert all(response.status_code == 201 for response in responses)
        assert len({response.json()["id"] for response in responses}) == 1
        unique = await asyncio.gather(
            *(
                client.post(
                    "/proposals",
                    json=proposal_payload(idempotency_key=f"different-{i}"),
                    headers=AUTH_ML,
                )
                for i in range(10)
            )
        )
        succeeded = sum(response.status_code == 201 for response in unique)
        assert all(response.status_code in (201, 402) for response in unique)
        assert (
            (await client.get("/connects", headers=AUTH_ML)).json()["balance"]
            == 52 - 8 * succeeded
            >= 0
        )


async def test_mcp_concurrent_receipts_holds_and_audit_immutability(setup):
    runtime, _app, who = setup
    service = WorkspaceService(runtime)
    request = EmailRequest(
        to="client@example.test",
        subject="Interview",
        body="Hello",
        idempotency_key="parallel-draft",
    )
    results = await asyncio.gather(*(service.email(who, request) for _ in range(8)))
    assert len({result["draft_id"] for result in results}) == 1
    async with runtime.sessions() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(EmailDraft)
                .where(EmailDraft.user_id == who.user_id)
            )
            == 1
        )
    slot = (await service.free_slots(who, 7))["slots"][0]

    async def create(key):
        request = HoldRequest(
            slot=Slot.model_validate(slot), title="Interview", idempotency_key=key
        )
        return await runtime.run(
            "create_hold",
            request.model_dump(mode="json"),
            lambda owner: service.hold(owner, request),
        )

    results = await asyncio.gather(create("slot-a"), create("slot-b"))
    assert sum(result["ok"] for result in results) == 1
    assert any(
        result["error"] and result["error"]["code"] == "slot_unavailable"
        for result in results
    )
    for statement in (
        "UPDATE audit_log SET action='changed' WHERE user_id=:user",
        "DELETE FROM audit_log WHERE user_id=:user",
    ):
        async with runtime.sessions() as session:
            with pytest.raises(DBAPIError):
                await session.execute(text(statement), {"user": who.user_id})
            await session.rollback()
    async with runtime.sessions() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.user_id == who.user_id)
            )
            == 2
        )


class LoseFirstWrite(httpx.AsyncBaseTransport):
    def __init__(self, app):
        self.inner = httpx.ASGITransport(app=app)
        self.lost = False

    async def handle_async_request(self, request):
        response = await self.inner.handle_async_request(request)
        if (
            request.method == "POST"
            and not json.loads(request.content).get("dry_run")
            and not self.lost
        ):
            self.lost = True
            await response.aclose()
            raise httpx.ReadTimeout("Response lost after server commit")
        return response


async def test_lost_response_and_process_receipt_recovery(setup):
    runtime, app, who = setup
    runtime.transport = LoseFirstWrite(app)
    request = ProposalRequest(
        job_id="job_ml",
        cover_letter="Python and pandas experience",
        idempotency_key="lost",
        expected_connects_cost=8,
    )
    async with runtime.sessions() as session:
        session.add(
            ApprovalGrant(
                user_id=who.user_id,
                tool="submit_proposal",
                idempotency_key=request.idempotency_key,
                payload_hash=fingerprint(
                    request.model_dump(mode="json", exclude={"dry_run"})
                ),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        await session.commit()
    first = await MarketplaceService(runtime).proposal(who, request, draft=False)
    # A fresh service instance uses the persisted receipt, not an in-memory cache.
    second = await MarketplaceService(runtime).proposal(who, request, draft=False)
    assert first == second
    async with app.state.sessionmaker() as session:
        assert await session.scalar(select(func.count()).select_from(SimProposal)) == 1
    assert (await MarketplaceService(runtime).adapter.get_connects_balance(who))[
        "balance"
    ] == 52


@pytest.mark.skipif(
    not os.getenv("FOUNDATION_TEST_REDIS_URL"), reason="requires isolated Redis test DB"
)
async def test_shared_redis_sliding_window():
    from redis.asyncio import Redis

    from mcp_servers.marketplace.adapters.gigsim import RATE_LIMIT

    redis = Redis.from_url(os.environ["FOUNDATION_TEST_REDIS_URL"])
    key = "test:mcp-quota:" + uuid.uuid4().hex
    try:
        results = await asyncio.gather(
            *(redis.eval(RATE_LIMIT, 1, key, 20) for _ in range(50))
        )
        assert results.count(0) == 20
        assert all(wait == 0 or 0 < wait <= 60000 for wait in results)
        assert await redis.zcard(key) == 20
    finally:
        await redis.delete(key, key + ":seq")
        await redis.aclose()
