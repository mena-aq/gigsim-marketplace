"""Exercise real MCP protocol calls with isolated app and simulator databases."""

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import httpx
import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.shared.memory import create_connected_server_and_client_session
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from apps.api.models import (
    ApprovalGrant,
    AuditLog,
    Base,
    EmailDraft,
    MCPCredential,
    ToolReceipt,
    User,
    WorkspaceHold,
)
from gigsim import scheduler
from gigsim.db import init_db
from gigsim.tests.conftest import make_app, seed_test_data
from mcp_servers.common.config import MCPSettings
from mcp_servers.common.runtime import Runtime
from mcp_servers.common.schemas import ProposalRequest
from mcp_servers.common.security import DatabaseTokenVerifier, fingerprint, token_hash
from mcp_servers.marketplace.server import create_server as marketplace
from mcp_servers.portfolio.server import create_server as portfolio
from mcp_servers.workspace.server import create_server as workspace


class Quota:
    def __init__(self):
        self.wait = 0
        self.calls = 0

    async def eval(self, *args):
        self.calls += 1
        return self.wait

    async def aclose(self):
        return None


@pytest.fixture
async def runtime(tmp_path):
    app = make_app()
    await init_db(app.state.engine)
    await seed_test_data(app)
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    root = tmp_path / "personas"
    for persona in ("ml_engineer", "fullstack_dev"):
        directory = root / persona
        (directory / "case_studies").mkdir(parents=True)
        (directory / "proposals").mkdir()
        (directory / "case_studies/one.md").write_text(
            "# Forecasting\nBuilt Python forecasting with pandas; reduced error by 12%."
        )
        (directory / "proposals/won_001.md").write_text(
            "---\noutcome: won\ndate: 2024-03-15\n---\nPython forecasting proposal."
        )
        (directory / "skills.json").write_text('{"skills":["python","pandas"]}')
        (directory / "cv.md").write_text("Python engineer")
        (directory / "reviews.md").write_text("Great Python work")
    instance = Runtime(
        MCPSettings(
            _env_file=None,
            mcp_persona_dir=root,
            gigsim_token_ml_engineer="test-token-ml",
            gigsim_token_fullstack_dev="test-token-fullstack",
        ),
        engine=engine,
        redis=Quota(),
        transport=httpx.ASGITransport(app=app),
    )
    async with instance.sessions() as session:
        session.add_all(
            [
                User(id="alice", email="alice@test.local", persona="ml_engineer"),
                User(id="bob", email="bob@test.local", persona="fullstack_dev"),
            ]
        )
        await session.flush()
        session.add(
            MCPCredential(user_id="alice", token_hash=token_hash("alice-secret"))
        )
        await session.commit()
    token = auth_context_var.set(
        AuthenticatedUser(
            AccessToken(
                token="test",
                subject="alice",
                client_id="alice",
                scopes=["gigbid"],
                claims={"persona": "ml_engineer"},
            )
        )
    )
    yield instance
    auth_context_var.reset(token)
    scheduler.cancel_all()
    await app.state.engine.dispose()
    await instance.close()


async def call(client, name, arguments=None):
    response = await client.call_tool(name, arguments or {})
    assert not response.isError, response.content
    return response.structuredContent


async def grant(runtime, tool, request, **changes):
    async with runtime.sessions() as session:
        session.add(
            ApprovalGrant(
                user_id="alice",
                tool=tool,
                idempotency_key=request.idempotency_key,
                payload_hash=fingerprint(
                    request.model_dump(mode="json", exclude={"dry_run"})
                ),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                **changes,
            )
        )
        await session.commit()


async def test_portfolio_resources_prompts_and_tenant_isolation(runtime):
    async with create_connected_server_and_client_session(portfolio(runtime)) as client:
        result = await call(
            client,
            "search_evidence",
            {
                "request": {
                    "requirement": "forecasting",
                    "filters": {"type": "case_study"},
                }
            },
        )
        assert result["ok"]
        evidence = result["data"]["items"][0]
        assert evidence["id"] == "ml_engineer:case_studies/one.md"
        assert evidence["date"] is None
        assert (await call(client, "get_case_study", {"id": evidence["id"]}))["data"][
            "text"
        ].endswith("12%.")
        assert (
            await call(
                client, "get_case_study", {"id": "fullstack_dev:case_studies/one.md"}
            )
        )["error"]["code"] == "not_found"
        assert (
            await call(client, "get_case_study", {"id": "ml_engineer:../skills.json"})
        )["error"]["code"] == "not_found"
        resource = await client.read_resource(
            "portfolio://case/" + quote(evidence["id"], safe="")
        )
        assert "12%" in resource.contents[0].text
        proposals = await call(
            client,
            "search_evidence",
            {"request": {"requirement": "python", "filters": {"outcome": "won"}}},
        )
        assert proposals["data"]["items"][0]["outcome"] == "won"
        assert (
            await call(
                client, "search_evidence", {"request": {"requirement": "nonexistent"}}
            )
        )["data"]["items"] == []
        assert (await call(client, "list_skills"))["data"]["skills"] == [
            "python",
            "pandas",
        ]
        assert len((await client.list_prompts()).prompts) == 1
        prompt = await client.get_prompt(
            "answer_screening_question", {"question": "Describe Python experience"}
        )
        assert "Describe Python experience" in prompt.messages[0].content.text
        assert len((await client.list_resource_templates()).resourceTemplates) == 2


async def test_marketplace_previews_approval_replay_and_audit(runtime):
    request = ProposalRequest(
        job_id="job_ml",
        cover_letter="Python forecasting",
        idempotency_key="bid-one",
        expected_connects_cost=8,
    )
    async with create_connected_server_and_client_session(
        marketplace(runtime)
    ) as client:
        assert (await call(client, "search_jobs", {"request": {"q": "churn"}}))["data"][
            "items"
        ][0]["id"] == "job_ml"
        assert (await call(client, "get_client_history", {"client_id": "client_good"}))[
            "data"
        ]["client"]["payment_verified"]
        before = (await call(client, "get_connects_balance"))["data"]["balance"]
        preview = await call(
            client,
            "submit_proposal",
            {"request": request.model_copy(update={"dry_run": True}).model_dump()},
        )
        assert preview["data"]["connects_cost"] == 8
        assert (await call(client, "get_connects_balance"))["data"]["balance"] == before
        denied = await call(
            client, "submit_proposal", {"request": request.model_dump()}
        )
        assert denied["error"]["code"] == "approval_required"
        await grant(runtime, "submit_proposal", request)
        sent = await call(client, "submit_proposal", {"request": request.model_dump()})
        assert sent["ok"]
        assert (
            await call(client, "submit_proposal", {"request": request.model_dump()})
        )["data"] == sent["data"]
        assert (await call(client, "get_connects_balance"))["data"][
            "balance"
        ] == before - 8
        altered = request.model_copy(update={"cover_letter": "Changed"})
        assert (
            await call(client, "submit_proposal", {"request": altered.model_dump()})
        )["error"]["code"] == "idempotency_conflict"
        from mcp_servers.common.schemas import MessageRequest

        message = MessageRequest(
            conversation_id="job_ml:ml_engineer",
            body="Contact alice@example.com +92 300 1234567",
            idempotency_key="msg-one",
        )
        assert (await call(client, "send_message", {"request": message.model_dump()}))[
            "error"
        ]["code"] == "approval_required"
        await grant(runtime, "send_message", message)
        first = await call(client, "send_message", {"request": message.model_dump()})
        assert first["ok"]
        assert (await call(client, "send_message", {"request": message.model_dump()}))[
            "data"
        ] == first["data"]
        messages = await call(
            client, "list_messages", {"conversation_id": message.conversation_id}
        )
        assert len(messages["data"]) == 1
        async with runtime.sessions() as session:
            audits = (await session.execute(select(AuditLog))).scalars().all()
            text = json.dumps([entry.payload for entry in audits])
            assert "alice@example.com" not in text
            assert "+92 300 1234567" not in text
            assert "[EMAIL]" in text
            assert (
                len((await session.execute(select(ToolReceipt))).scalars().all()) == 2
            )


async def test_workspace_persistence_dry_run_and_overlap(runtime):
    async with create_connected_server_and_client_session(workspace(runtime)) as client:
        free = await call(client, "get_free_slots", {"days_ahead": 7})
        slot = free["data"]["slots"][0]
        payload = {
            "slot": slot,
            "title": "Interview",
            "idempotency_key": "hold-one",
            "dry_run": True,
        }
        assert (await call(client, "create_hold", {"request": payload}))["data"][
            "status"
        ] == "dry_run"
        async with runtime.sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(WorkspaceHold))
                == 0
            )
        payload["dry_run"] = False
        held = await call(client, "create_hold", {"request": payload})
        assert held["ok"]
        assert (await call(client, "create_hold", {"request": payload}))[
            "data"
        ] == held["data"]
        payload["idempotency_key"] = "hold-two"
        assert (await call(client, "create_hold", {"request": payload}))["error"][
            "code"
        ] == "slot_unavailable"
        email = {
            "to": "client@example.com",
            "subject": "Meeting",
            "body": "Hello",
            "idempotency_key": "email-one",
        }
        assert (await call(client, "create_email_draft", {"request": email}))["ok"]
        assert (await call(client, "create_email_draft", {"request": email}))["ok"]
    async with runtime.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(EmailDraft)) == 1
        assert (
            await session.scalar(select(func.count()).select_from(WorkspaceHold)) == 1
        )


async def test_auth_quota_validation_and_allowlists(runtime):
    verifier = DatabaseTokenVerifier(runtime.sessions)
    assert await verifier.verify_token("wrong") is None
    assert (await verifier.verify_token("alice-secret")).subject == "alice"
    runtime.redis.wait = 60000
    async with create_connected_server_and_client_session(
        marketplace(runtime)
    ) as client:
        limited = await call(client, "get_connects_balance")
        assert limited["error"]["code"] == "rate_limited"
        assert limited["error"]["retry_after"] == 60
        invalid = await client.call_tool("search_jobs", {"request": {"page": 0}})
        assert invalid.isError
    from agent.mcp_client import MCPGateway
    from mcp_servers.common.security import ToolFailure

    gateway = MCPGateway("unused", "analyst", "trace-one")
    assert await gateway.tools() == []
    with pytest.raises(ToolFailure, match="role"):
        await gateway.call("submit_proposal", {})


async def test_http_authentication_and_validation(runtime):
    from fastapi.testclient import TestClient

    from mcp_servers.common.server import http_app

    with TestClient(
        http_app(portfolio(runtime), runtime), base_url="http://localhost:8101"
    ) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/mcp").status_code == 401
        assert (
            client.get("/mcp", headers={"Authorization": "Bearer wrong"}).status_code
            == 401
        )
        response = client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer alice-secret",
                "Accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
        )
        assert response.status_code == 200
        assert "serverInfo" in response.json()["result"]


async def test_missing_corpus_and_tampered_approval(runtime):
    runtime.settings.mcp_persona_dir = runtime.settings.mcp_persona_dir / "absent"
    async with create_connected_server_and_client_session(portfolio(runtime)) as client:
        result = await call(client, "list_skills")
        assert result["error"]["code"] == "corpus_unavailable"
    request = ProposalRequest(
        job_id="job_ml",
        cover_letter="Original",
        idempotency_key="approved",
        expected_connects_cost=8,
    )
    await grant(runtime, "submit_proposal", request)
    async with create_connected_server_and_client_session(
        marketplace(runtime)
    ) as client:
        changed = request.model_copy(update={"cover_letter": "Tampered"})
        denied = await call(
            client, "submit_proposal", {"request": changed.model_dump()}
        )
        assert denied["error"]["code"] == "approval_required"
        assert (await call(client, "get_connects_balance"))["data"]["balance"] == 60


async def test_upstream_retry_exhaustion_and_retry_after(runtime, monkeypatch):
    from unittest.mock import AsyncMock

    from mcp_servers.common.security import Identity, ToolFailure
    from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter

    monkeypatch.setattr(
        "mcp_servers.marketplace.adapters.gigsim.asyncio.sleep", AsyncMock()
    )
    runtime.transport = httpx.MockTransport(
        lambda request: httpx.Response(500, json={"error": "failed"})
    )
    with pytest.raises(ToolFailure) as error:
        await GigSimAdapter(runtime).get_connects_balance(
            Identity("alice", "ml_engineer")
        )
    assert error.value.retryable
    assert runtime.redis.calls == 3
    runtime.redis.calls = 0
    runtime.transport = httpx.MockTransport(
        lambda request: httpx.Response(429, headers={"Retry-After": "60"})
    )
    with pytest.raises(ToolFailure) as error:
        await GigSimAdapter(runtime).get_connects_balance(
            Identity("alice", "ml_engineer")
        )
    assert error.value.retry_after == 60
    assert runtime.redis.calls == 1


def test_log_redaction():
    import logging

    from mcp_servers.common.security import RedactLogs

    record = logging.LogRecord(
        "sdk",
        logging.ERROR,
        "",
        1,
        "Contact alice@example.com +92 300 1234567 Authorization: Bearer private-token",
        (),
        None,
    )
    assert RedactLogs().filter(record)
    assert "private-token" not in record.getMessage()
    assert "alice@example.com" not in record.getMessage()
