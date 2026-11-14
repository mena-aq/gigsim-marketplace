"""Trusted run coordinator: tenant ownership, approval grants and worker recovery."""

import hashlib
import os
import uuid
from datetime import UTC, datetime, timedelta

from langgraph.types import Command, Overwrite
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from agent.config import load_graph_config
from agent.execution import GraphServices
from agent.graphs.bid_graph import build_bid_graph
from agent.graphs.conversation_graph import build_conversation_graph
from apps.api.models import (
    ApprovalGrant,
    AuditLog,
    GraphRun,
    MCPCredential,
    ToolReceipt,
    User,
)
from mcp_servers.common.errors import ToolFailure
from mcp_servers.common.security import fingerprint, mask, token_hash


def thread_config(run):
    return {
        "configurable": {"thread_id": run.user_id + ":" + run.id},
        "recursion_limit": 100,
    }


class RunCoordinator:
    def __init__(self, engine, saver, store):
        self.engine = engine
        self.sessions = async_sessionmaker(engine, expire_on_commit=False)
        self.saver = saver
        self.store = store
        self.config = load_graph_config()

    async def audit(self, state, action, payload):
        async with self.sessions() as session:
            session.add(
                AuditLog(
                    user_id=state["user_id"],
                    trace_id=state["trace_id"],
                    action=action,
                    payload=mask(payload),
                )
            )
            await session.commit()

    async def grant(self, state, tool, request):
        digest = fingerprint(
            {key: value for key, value in request.items() if key != "dry_run"}
        )
        async with self.sessions() as session, session.begin():
            await session.execute(
                select(User).where(User.id == state["user_id"]).with_for_update()
            )
            receipt = await session.scalar(
                select(ToolReceipt).where(
                    ToolReceipt.user_id == state["user_id"],
                    ToolReceipt.tool == tool,
                    ToolReceipt.idempotency_key == request["idempotency_key"],
                )
            )
            if receipt:
                if receipt.payload_hash != digest:
                    raise ToolFailure(
                        "idempotency_conflict",
                        "The reviewed key already belongs to another request",
                    )
                return
            # Timestamp comes from the trusted authenticated API, not client input.
            run = await session.get(GraphRun, state["thread_id"])
            accepted = run.resume if run else None
            if (
                not accepted
                or accepted.get("action") != "approve"
                or accepted.get("review_hash") != state["approval"]["review_hash"]
            ):
                raise ToolFailure(
                    "approval_required", "No authenticated human approval is recorded"
                )
            expires = datetime.fromisoformat(accepted["accepted_at"]) + timedelta(
                minutes=self.config["orchestration"]["approval_minutes"]
            )
            if expires <= datetime.now(UTC):
                raise ToolFailure(
                    "approval_expired", "Human approval expired before submission"
                )
            grant = await session.scalar(
                select(ApprovalGrant).where(
                    ApprovalGrant.user_id == state["user_id"],
                    ApprovalGrant.tool == tool,
                    ApprovalGrant.idempotency_key == request["idempotency_key"],
                    ApprovalGrant.payload_hash == digest,
                    ApprovalGrant.consumed_at.is_(None),
                )
            )
            if grant is None:
                session.add(
                    ApprovalGrant(
                        user_id=state["user_id"],
                        tool=tool,
                        payload_hash=digest,
                        idempotency_key=request["idempotency_key"],
                        expires_at=expires,
                    )
                )

    def graph(self, run, token=""):
        services = GraphServices(
            token=token,
            config=self.config,
            store=self.store,
            audit=self.audit,
            grant=self.grant,
        )
        builder = build_bid_graph if run.kind == "bid" else build_conversation_graph
        return builder(services, checkpointer=self.saver, store=self.store)

    async def token_for(self, run):
        async with self.sessions() as session:
            user = await session.get(User, run.user_id)
            if user is None:
                raise ToolFailure("user_unavailable", "Run owner is unavailable")
            token = os.getenv("MCP_TOKEN_" + user.persona.upper(), "")
            credential = await session.get(MCPCredential, token_hash(token))
            if not token or not credential or credential.user_id != run.user_id:
                raise ToolFailure(
                    "credential_unavailable",
                    "Configured worker credential does not match the run owner",
                )
            return token

    async def snapshot(self, run):
        return await self.graph(run).aget_state(thread_config(run))

    async def process(self, run_id):
        # Transaction advisory locks release on rollback/connection death. Duplicate queue
        # deliveries never execute the same checkpoint concurrently.
        lock = int.from_bytes(
            hashlib.sha256(run_id.encode()).digest()[:8], "big", signed=True
        )
        async with self.engine.begin() as connection:
            locked = await connection.scalar(
                text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": lock}
            )
            if not locked:
                return
            await self._process(run_id)

    async def _process(self, run_id):
        async with self.sessions() as session:
            run = await session.get(GraphRun, run_id)
            if run is None or run.status not in {"queued", "running", "retry_wait"}:
                return
            if run.retry_at and run.retry_at > datetime.now(UTC):
                return
            run.status = "running"
            run.attempts += 1
            await session.commit()
            try:
                graph = self.graph(run, await self.token_for(run))
                config = thread_config(run)
                snapshot = await graph.aget_state(config)
                if (
                    run.resume
                    and run.resume.get("replay_state")
                    and not snapshot.values
                ):
                    replay_values = {
                        **run.resume["replay_state"],
                        "steps": Overwrite(0),
                        "tokens": Overwrite(0),
                        "errors": Overwrite({}),
                        "analyses": Overwrite(
                            run.resume["replay_state"].get("analyses", {})
                        ),
                    }
                    await graph.aupdate_state(config, replay_values, as_node="stop")
                    snapshot = await graph.aget_state(config)
                if (
                    run.resume
                    and run.resume.get("next_turn")
                    and snapshot.values.get("turn_id") != run.resume["next_turn"]
                ):
                    command = {
                        **snapshot.values,
                        "turn_id": run.resume["next_turn"],
                        "steps": 0,
                        "tokens": 0,
                        "errors": Overwrite({}),
                        "analyses": Overwrite({}),
                        "edits": [],
                        "approval": {},
                        "request": {},
                        "preview": {},
                        "result": {},
                        "status": "running",
                    }
                elif (
                    run.resume
                    and run.resume.get("replay_node")
                    and not snapshot.next
                    and snapshot.values.get("status") == "running"
                ):
                    command = Command(goto=run.resume["replay_node"])
                elif snapshot.values:
                    # After a crash the checkpoint may already be awaiting review
                    # or complete, even if the outbox still says running.
                    pending = [
                        item for task in snapshot.tasks for item in task.interrupts
                    ]
                    if pending and not run.resume:
                        run.status = "awaiting_approval"
                        await session.commit()
                        return
                    if not snapshot.next:
                        run.status = snapshot.values.get("status", "needs_attention")
                        await session.commit()
                        return
                    command = (
                        Command(
                            resume={
                                key: value
                                for key, value in run.resume.items()
                                if key != "accepted_at"
                            }
                        )
                        if pending and run.resume
                        else None
                    )
                else:
                    command = {
                        "user_id": run.user_id,
                        "thread_id": run.id,
                        "trace_id": run.trace_id,
                        "turn_id": "initial",
                        "job_id"
                        if run.kind == "bid"
                        else "conversation_id": run.target,
                        "steps": 0,
                        "tokens": 0,
                        "errors": {},
                        "analyses": {},
                        "edits": [],
                    }
                await graph.ainvoke(command, config, durability="sync")
                snapshot = await graph.aget_state(config)
                run.status = (
                    "awaiting_approval"
                    if any(task.interrupts for task in snapshot.tasks)
                    else snapshot.values.get("status", "needs_attention")
                )
                if run.status == "awaiting_approval":
                    run.resume = None
                run.error = next(iter(snapshot.values.get("errors", {}).values()), None)
                run.retry_at = None
            except ToolFailure as exc:
                run.error = {"code": exc.code, "message": exc.message}
                if (
                    exc.retryable
                    and run.attempts < self.config["orchestration"]["max_run_attempts"]
                ):
                    run.status = "retry_wait"
                    run.retry_at = datetime.now(UTC) + timedelta(
                        seconds=max(exc.retry_after or 0, min(300, 2**run.attempts))
                    )
                else:
                    run.status = "dead_letter"
            except Exception as exc:  # noqa: BLE001 -- preserve the durable dead-letter record
                # No exception repr: SDK validation errors may contain raw inputs.
                run.error = {"code": "execution_failed", "message": type(exc).__name__}
                run.status = "dead_letter"
            await session.commit()


def new_run(user_id, kind, target, turn="initial"):
    return GraphRun(
        id=str(uuid.uuid4()),
        user_id=user_id,
        kind=kind,
        target=target,
        turn=turn,
        trace_id=str(uuid.uuid4()),
        status="queued",
        attempts=0,
    )
