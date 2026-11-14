"""Opt-in restart/concurrency tests in a disposable PostgreSQL schema.

GRAPH_TEST_DATABASE_URL points at a local PostgreSQL server. No production rows
or simulator database are read or changed; model outputs are deterministic.
"""

import asyncio
import os
import uuid
from urllib.parse import quote

import httpx
import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.shared.memory import create_connected_server_and_client_session
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from agent.execution import GraphServices, review_payload
from agent.graphs.bid_graph import build_bid_graph
from agent.persistence import connection_string, graph_storage, setup_storage
from agent.runs import RunCoordinator, new_run
from apps.api.main import create_app
from apps.api.models import AuditLog, Base, GraphRun, MCPCredential, ToolReceipt, User
from apps.api.orchestration import coordinator
from gigsim import scheduler
from gigsim.db import init_db
from gigsim.models import Connects
from gigsim.models import Proposal as SimProposal
from gigsim.tests.conftest import make_app, seed_test_data
from mcp_servers.common.config import MCPSettings
from mcp_servers.common.errors import ToolFailure
from mcp_servers.common.runtime import Runtime
from mcp_servers.common.security import token_hash
from mcp_servers.marketplace.server import create_server
from tests.unit.test_graphs import Model, Tools

pytestmark = pytest.mark.skipif(
    not os.getenv("GRAPH_TEST_DATABASE_URL"), reason="requires PostgreSQL"
)


@pytest.fixture
async def database(monkeypatch):
    url = os.environ["GRAPH_TEST_DATABASE_URL"]
    admin = create_async_engine(url)
    schema = "graph_test_" + uuid.uuid4().hex
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        url, connect_args={"server_settings": {"search_path": schema}}
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    dsn = connection_string(url) + "?options=" + quote("-csearch_path=" + schema)
    await setup_storage(dsn)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        session.add_all(
            [
                User(id="alice", email="alice@example.test", persona="ml_engineer"),
                User(id="bob", email="bob@example.test", persona="fullstack_dev"),
            ]
        )
        await session.flush()
        session.add(
            MCPCredential(user_id="alice", token_hash=token_hash("graph-test-key"))
        )
        session.add(MCPCredential(user_id="bob", token_hash=token_hash("bob-test-key")))
        await session.commit()
    monkeypatch.setenv("MCP_TOKEN_ML_ENGINEER", "graph-test-key")
    try:
        yield engine, dsn
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


async def test_postgres_restart_approval_and_exactly_one_simulator_spend(database):
    engine, dsn = database
    app = make_app()
    await init_db(app.state.engine)
    await seed_test_data(app)

    class Quota:
        async def eval(self, *args):
            return 0

        async def aclose(self):
            return None

    runtime = Runtime(
        MCPSettings(_env_file=None, gigsim_token_ml_engineer="test-token-ml"),
        engine=engine,
        redis=Quota(),
        transport=httpx.ASGITransport(app=app),
    )
    market = create_server(runtime)
    fallback = Tools()
    model = Model()

    async def install(service):
        def gateway(token, role, trace):
            fake = fallback.gateway(token, role, trace)

            class Gateway:
                async def call(self, name, args):
                    if name not in {
                        "get_job",
                        "search_jobs",
                        "get_client_history",
                        "get_connects_balance",
                        "submit_proposal",
                    }:
                        return await fake.call(name, args)
                    auth = auth_context_var.set(
                        AuthenticatedUser(
                            AccessToken(
                                token="test",
                                client_id="alice",
                                subject="alice",
                                scopes=["gigbid"],
                                claims={"persona": "ml_engineer"},
                            )
                        )
                    )
                    try:
                        async with create_connected_server_and_client_session(
                            market
                        ) as client:
                            response = (
                                await client.call_tool(name, args)
                            ).structuredContent
                            if not response["ok"]:
                                error = response["error"]
                                raise ToolFailure(
                                    error["code"],
                                    error["message"],
                                    error["retryable"],
                                    error["retry_after"],
                                )
                            return response["data"]
                    finally:
                        auth_context_var.reset(auth)

            return Gateway()

        def graph(run, token=""):
            return build_bid_graph(
                GraphServices(
                    token=token,
                    model=model,
                    gateway_factory=gateway,
                    config=service.config,
                    store=service.store,
                    audit=service.audit,
                    grant=service.grant,
                ),
                checkpointer=service.saver,
                store=service.store,
            )

        service.graph = graph

    try:
        async with graph_storage(dsn) as (saver, store):
            service = RunCoordinator(engine, saver, store)
            await install(service)
            run = new_run("alice", "bid", "job_ml")
            async with service.sessions() as session:
                session.add(run)
                await session.commit()
            await service.process(run.id)
            async with service.sessions() as session:
                saved = await session.get(GraphRun, run.id)
                assert saved.status == "awaiting_approval", saved.error
                snapshot = await service.snapshot(saved)
                assert not await session.scalar(
                    select(func.count()).select_from(ToolReceipt)
                )
            api = create_app()
            api.state.engine = engine

            async def override():
                yield service

            api.dependency_overrides[coordinator] = override
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=api), base_url="http://test"
            ) as client:
                assert (await client.get("/agent/runs")).status_code == 401
                assert (
                    await client.get(
                        "/agent/runs/" + run.id,
                        headers={"Authorization": "Bearer bob-test-key"},
                    )
                ).status_code == 404
                headers = {"Authorization": "Bearer graph-test-key"}
                endpoint = "/agent/runs/" + run.id + "/approval"
                assert (
                    await client.post(
                        endpoint,
                        headers=headers,
                        json={"action": "approve", "review_hash": "0" * 64},
                    )
                ).status_code == 409
                body = {
                    "action": "approve",
                    "review_hash": review_payload(snapshot.values)["review_hash"],
                }
                assert (
                    await client.post(endpoint, headers=headers, json=body)
                ).status_code == 202
                assert (
                    await client.post(endpoint, headers=headers, json=body)
                ).status_code == 409
        # Close/reopen both saver and store, and recreate the coordinator.
        async with graph_storage(dsn) as (saver, store):
            restarted = RunCoordinator(engine, saver, store)
            await install(restarted)
            await asyncio.gather(restarted.process(run.id), restarted.process(run.id))
            async with restarted.sessions() as session:
                saved = await session.get(GraphRun, run.id)
                assert saved.status == "sent", saved.error
                assert (
                    await session.scalar(select(func.count()).select_from(ToolReceipt))
                    == 1
                )
                # Simulate a crash after graph completion but before outbox status commit.
                saved.status = "running"
                await session.commit()
            await restarted.process(run.id)
            async with restarted.sessions() as session:
                assert (await session.get(GraphRun, run.id)).status == "sent"
                audits = (await session.scalars(select(AuditLog))).all()
                assert any(record.action == "node.execute" for record in audits)
                assert any(record.action == "tool.submit_proposal" for record in audits)
            assert model.calls.count("writer") == 1
            api.dependency_overrides[coordinator] = lambda: restarted
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=api), base_url="http://test"
            ) as client:
                headers = {"Authorization": "Bearer graph-test-key"}
                history = (
                    await client.get(
                        "/agent/runs/" + run.id + "/history", headers=headers
                    )
                ).json()
                replay = await client.post(
                    "/agent/runs/" + run.id + "/replay",
                    headers=headers,
                    json={
                        "checkpoint_id": history[0]["checkpoint_id"],
                        "node": "execute",
                    },
                )
                assert replay.status_code == 202, replay.text
                fork_id = replay.json()["id"]
                await restarted.process(fork_id)
                async with restarted.sessions() as session:
                    fork = await session.get(GraphRun, fork_id)
                    assert fork.status == "awaiting_approval", fork.error
                    assert (
                        await session.scalar(
                            select(func.count()).select_from(ToolReceipt)
                        )
                        == 1
                    )
        async with app.state.sessionmaker() as session:
            assert (
                await session.scalar(select(func.count()).select_from(SimProposal)) == 1
            )
            assert (await session.get(Connects, "ml_engineer")).balance == 52
    finally:
        scheduler.cancel_all()
        await app.state.engine.dispose()
        await runtime.redis.aclose()
