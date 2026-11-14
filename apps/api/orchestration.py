"""Authenticated run and review API. Long work executes only in the worker."""

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from agent.execution import review_payload
from agent.handoffs import ApprovalRequest
from agent.marketplace_port import MCPMarketplacePort
from agent.mcp_client import MCPGateway
from agent.memory.store import promote_outcome
from agent.persistence import graph_storage
from agent.runs import RunCoordinator, new_run, thread_config
from apps.api.models import (
    ApprovalGrant,
    AuditLog,
    GraphRun,
    RetiredEvidence,
    ToolReceipt,
    User,
)
from mcp_servers.common.schemas import SearchJobs
from mcp_servers.common.security import DatabaseTokenVerifier, mask

router = APIRouter(prefix="/agent", tags=["orchestration"])
bearer = HTTPBearer(auto_error=False)


async def authenticated(
    request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)
):
    if not credentials:
        raise HTTPException(401, "Sign in with your provisioned workspace access key")
    verifier = DatabaseTokenVerifier(async_sessionmaker(request.app.state.engine))
    token = await verifier.verify_token(credentials.credentials)
    if token is None:
        raise HTTPException(401, "Invalid access key")
    return token


async def coordinator(request: Request, user=Depends(authenticated)):
    async with graph_storage(request.app.state.settings.database_url) as (saver, store):
        yield RunCoordinator(request.app.state.engine, saver, store)


async def owned(coordinator, user_id, run_id, session=None):
    if session is None:
        async with coordinator.sessions() as scoped_session:
            return await owned(coordinator, user_id, run_id, scoped_session)
    run = await session.scalar(
        select(GraphRun).where(GraphRun.id == run_id, GraphRun.user_id == user_id)
    )
    if run is None:
        raise HTTPException(404, "Run not found")
    return run


class StartRun(BaseModel):
    kind: Literal["bid", "conversation"]
    target: str = Field(min_length=1, max_length=160)


class RunSummary(BaseModel):
    id: str
    kind: str
    target: str
    status: str
    trace_id: str
    attempts: int
    error: dict | None = None
    created_at: datetime | None = None
    title: str | None = None


class RunDetail(RunSummary):
    state: dict
    review: dict | None = None


def summary(run):
    return RunSummary.model_validate(run, from_attributes=True)


@router.get("/me")
async def me(user=Depends(authenticated)) -> dict:
    return {"user_id": user.subject, "persona": user.claims["persona"]}


@router.get("/jobs")
async def jobs(q: str = "", user=Depends(authenticated)) -> dict:
    from mcp_servers.common.errors import ToolFailure

    try:
        port = MCPMarketplacePort(
            MCPGateway(user.token, "scout", "search:" + user.subject)
        )
        return (await port.search_jobs(SearchJobs(q=q))).model_dump(mode="json")
    except ToolFailure as exc:
        raise HTTPException(503, "Marketplace unavailable — work is queued") from exc


@router.get("/jobs/{job_id}")
async def job(job_id: str, user=Depends(authenticated)) -> dict:
    from mcp_servers.common.errors import ToolFailure

    try:
        port = MCPMarketplacePort(
            MCPGateway(user.token, "scout", "job:" + user.subject + ":" + job_id)
        )
        return (await port.get_job(job_id)).model_dump(mode="json")
    except ToolFailure as exc:
        if exc.retryable:
            raise HTTPException(
                503, "Marketplace unavailable — work is queued"
            ) from exc
        raise HTTPException(404, "Job not found") from exc


@router.get("/conversations")
async def conversations(request: Request, user=Depends(authenticated)) -> list[dict]:
    """Client conversations on submitted proposals, with any reply run already started."""
    from mcp_servers.common.errors import ToolFailure

    try:
        liaison = MCPMarketplacePort(
            MCPGateway(user.token, "liaison", "conversations:" + user.subject)
        )
        items = await liaison.list_conversations()
    except ToolFailure as exc:
        raise HTTPException(503, "Marketplace unavailable — work is queued") from exc
    scout = MCPMarketplacePort(
        MCPGateway(user.token, "scout", "conversation-titles:" + user.subject)
    )

    async def title(job_id: str) -> str | None:
        try:
            return (await scout.get_job(job_id)).title
        except ToolFailure:
            return None

    titles = await asyncio.gather(*(title(item.job_id) for item in items))
    async with async_sessionmaker(request.app.state.engine)() as session:
        rows = (
            await session.scalars(
                select(GraphRun)
                .where(GraphRun.user_id == user.subject, GraphRun.kind == "conversation")
                .order_by(GraphRun.created_at)
            )
        ).all()
    latest = {row.target: row for row in rows}
    return [
        {
            **item.model_dump(mode="json"),
            "job_title": name,
            "run": (
                {"id": latest[item.conversation_id].id, "status": latest[item.conversation_id].status}
                if item.conversation_id in latest
                else None
            ),
        }
        for item, name in zip(items, titles, strict=True)
    ]


@router.post("/runs", response_model=RunSummary, status_code=202)
async def start(body: StartRun, request: Request, user=Depends(authenticated)):
    sessions = async_sessionmaker(request.app.state.engine, expire_on_commit=False)
    async with sessions() as session:
        existing = await session.scalar(
            select(GraphRun).where(
                GraphRun.user_id == user.subject,
                GraphRun.kind == body.kind,
                GraphRun.target == body.target,
                GraphRun.turn == "initial",
            )
        )
        if existing:
            return summary(existing)
        run = new_run(user.subject, body.kind, body.target)
        session.add(run)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            run = await session.scalar(
                select(GraphRun).where(
                    GraphRun.user_id == user.subject,
                    GraphRun.kind == body.kind,
                    GraphRun.target == body.target,
                    GraphRun.turn == "initial",
                )
            )
        return summary(run)


@router.get("/runs", response_model=list[RunSummary])
async def runs(request: Request, user=Depends(authenticated)):
    from mcp_servers.common.errors import ToolFailure

    async with async_sessionmaker(request.app.state.engine)() as session:
        rows = (
            await session.scalars(
                select(GraphRun)
                .where(GraphRun.user_id == user.subject)
                .order_by(GraphRun.created_at.desc())
                .limit(100)
            )
        ).all()
    items = [summary(row) for row in rows]
    scout = MCPMarketplacePort(
        MCPGateway(user.token, "scout", "run-titles:" + user.subject)
    )
    cache: dict[str, str | None] = {}

    async def title(job_id: str) -> str | None:
        try:
            return (await scout.get_job(job_id)).title
        except ToolFailure:
            return None

    # Titles are a convenience: look up the newest runs only, and never fail the
    # list when the marketplace is down.
    wanted = {
        item.target.split(":")[0] for item in items[:30] if item.target.split(":")[0]
    }
    for job_id, found in zip(
        wanted, await asyncio.gather(*(title(job) for job in wanted)), strict=True
    ):
        cache[job_id] = found
    for item in items:
        item.title = cache.get(item.target.split(":")[0])
    return items


@router.get("/runs/{run_id}", response_model=RunDetail)
async def detail(
    run_id: str, user=Depends(authenticated), service=Depends(coordinator)
):
    run = await owned(service, user.subject, run_id)
    snapshot = await service.snapshot(run)
    review = (
        review_payload(snapshot.values)
        if run.status == "awaiting_approval" and snapshot.values.get("preview")
        else None
    )
    return RunDetail(**summary(run).model_dump(), state=snapshot.values, review=review)


@router.post("/runs/{run_id}/approval", response_model=RunSummary, status_code=202)
async def approve(
    run_id: str,
    body: ApprovalRequest,
    user=Depends(authenticated),
    service=Depends(coordinator),
):
    async with service.sessions() as session, session.begin():
        run = await session.scalar(
            select(GraphRun)
            .where(GraphRun.id == run_id, GraphRun.user_id == user.subject)
            .with_for_update()
        )
        if run is None:
            raise HTTPException(404, "Run not found")
        if run.status != "awaiting_approval":
            raise HTTPException(409, "This run is not awaiting review")
        snapshot = await service.snapshot(run)
        if (
            not any(task.interrupts for task in snapshot.tasks)
            or review_payload(snapshot.values)["review_hash"] != body.review_hash
        ):
            raise HTTPException(
                409, "This review has changed; refresh before approving"
            )
        run.resume = {
            **body.model_dump(mode="json"),
            "accepted_at": datetime.now(UTC).isoformat(),
        }
        run.status = "queued"
        run.attempts = 0
        run.retry_at = None
        session.add(
            AuditLog(
                user_id=user.subject,
                trace_id=run.trace_id,
                action="human." + body.action,
                payload=mask(
                    {"run_id": run.id, "decision": body.model_dump(mode="json")}
                ),
            )
        )
        return summary(run)


@router.post("/runs/{run_id}/continue", response_model=RunSummary, status_code=202)
async def continue_conversation(
    run_id: str, user=Depends(authenticated), service=Depends(coordinator)
):
    async with service.sessions() as session, session.begin():
        run = await session.scalar(
            select(GraphRun)
            .where(GraphRun.id == run_id, GraphRun.user_id == user.subject)
            .with_for_update()
        )
        if run is None:
            raise HTTPException(404, "Run not found")
        if run.kind != "conversation" or run.status not in {
            "sent",
            "rejected",
            "blocked",
        }:
            raise HTTPException(409, "Finish the current conversation turn first")
        run.resume = {"next_turn": uuid.uuid4().hex[:12]}
        run.status = "queued"
        run.attempts = 0
        run.retry_at = None
        return summary(run)


class ReplayRequest(BaseModel):
    checkpoint_id: str = Field(min_length=1, max_length=128)
    node: str = Field(min_length=1, max_length=64)


@router.post("/runs/{run_id}/replay", response_model=RunSummary, status_code=202)
async def replay(
    run_id: str,
    body: ReplayRequest,
    user=Depends(authenticated),
    service=Depends(coordinator),
):
    original = await owned(service, user.subject, run_id)
    graph = service.graph(original)
    if body.node not in graph.nodes or body.node.startswith("__"):
        raise HTTPException(422, "Unknown graph node")
    checkpoint = {
        "configurable": {
            **thread_config(original)["configurable"],
            "checkpoint_id": body.checkpoint_id,
        }
    }
    snapshot = await graph.aget_state(checkpoint)
    if not snapshot.values:
        raise HTTPException(404, "Checkpoint not found")
    # Forks never inherit send authorization. Replaying a send or approval restarts
    # verification and creates a new preview/interrupt with a fresh write key.
    node = body.node
    if node in {"execute", "approval", "preview", "learn", "critic", "compliance"}:
        node = (
            "verify"
            if snapshot.values.get("draft")
            else ("scout" if original.kind == "bid" else "read_messages")
        )
    run = new_run(
        user.subject, original.kind, original.target, "replay:" + uuid.uuid4().hex
    )
    values = {
        **snapshot.values,
        "thread_id": run.id,
        "trace_id": run.trace_id,
        "steps": 0,
        "tokens": 0,
        "errors": {},
        "approval": {},
        "preview": {},
        "request": {},
        "result": {},
        "edits": [],
        "revisions": -1 if node == "writer" else 0,
        "verification_failed": False,
        "verification": {},
        "status": "running",
    }
    run.resume = {"replay_node": node, "replay_state": values}
    async with service.sessions() as session:
        session.add(run)
        await session.commit()
    await service.audit(
        values,
        "human.replay",
        {"source_run": original.id, "checkpoint_id": body.checkpoint_id, "node": node},
    )
    return summary(run)


@router.get("/runs/{run_id}/history")
async def history(
    run_id: str, user=Depends(authenticated), service=Depends(coordinator)
) -> list[dict]:
    run = await owned(service, user.subject, run_id)
    return [
        {
            "checkpoint_id": snap.config["configurable"].get("checkpoint_id"),
            "next": list(snap.next),
            "created_at": snap.created_at,
            "status": snap.values.get("status"),
        }
        async for snap in service.graph(run).aget_state_history(
            thread_config(run), limit=100
        )
    ]


@router.get("/runs/{run_id}/decision")
async def decision_trace(
    run_id: str, user=Depends(authenticated), service=Depends(coordinator)
) -> dict:
    """Explain the bid/watch/skip decision: scores vs thresholds plus the node timeline."""
    from agent.config import load_graph_config

    run = await owned(service, user.subject, run_id)
    state = (await service.snapshot(run)).values
    thresholds = load_graph_config()["thresholds"]
    analyses = state.get("analyses", {})
    risk = analyses.get("risk", {})
    fit = analyses.get("fit", {})
    async with service.sessions() as session:
        rows = (
            await session.scalars(
                select(AuditLog)
                .where(
                    AuditLog.user_id == user.subject,
                    AuditLog.trace_id == run.trace_id,
                    AuditLog.action.like("node.%"),
                )
                .order_by(AuditLog.created_at, AuditLog.id)
            )
        ).all()
    decision = state.get("decision") or {}
    driver = {"skip": "risk", "watch": "fit"}.get(decision.get("action"))
    return {
        "decision": decision or None,
        "driver": driver,
        "risk": {
            "score": risk.get("score"),
            "flags": risk.get("flags", []),
            "explanation": risk.get("explanation"),
            "maximum": thresholds["maximum_risk_score"],
        },
        "fit": {
            "score": fit.get("score"),
            "matched_skills": fit.get("matched_skills", []),
            "missing_skills": fit.get("missing_skills", []),
            "minimum": thresholds["minimum_fit_score"],
        },
        "nodes": [
            {
                "node": row.action.removeprefix("node."),
                "seconds": (row.payload or {}).get("seconds"),
                "error": (row.payload or {}).get("error"),
                "update_keys": sorted(((row.payload or {}).get("update") or {}).keys()),
            }
            for row in rows
        ],
    }


@router.get("/runs/{run_id}/submission")
async def submission(
    run_id: str, user=Depends(authenticated), service=Depends(coordinator)
) -> dict:
    """Evidence that an approved send happened exactly once, even across restarts."""
    run = await owned(service, user.subject, run_id)
    state = (await service.snapshot(run)).values
    request = state.get("request") or {}
    key = request.get("idempotency_key")
    tool = "send_message" if state.get("conversation_id") else "submit_proposal"
    async with service.sessions() as session:
        receipts = (
            await session.scalars(
                select(ToolReceipt).where(
                    ToolReceipt.user_id == user.subject,
                    ToolReceipt.tool == tool,
                    ToolReceipt.idempotency_key == key,
                )
            )
        ).all()
        grants = (
            await session.scalars(
                select(ApprovalGrant).where(
                    ApprovalGrant.user_id == user.subject,
                    ApprovalGrant.tool == tool,
                    ApprovalGrant.idempotency_key == key,
                )
            )
        ).all()
        attempts = (
            await session.scalars(
                select(AuditLog).where(
                    AuditLog.user_id == user.subject,
                    AuditLog.trace_id == run.trace_id,
                    AuditLog.action == "tool." + tool,
                )
            )
        ).all()
    return {
        "status": run.status,
        "worker_attempts": run.attempts,
        "tool": tool,
        "idempotency_key": key,
        "approved_at": (run.resume or {}).get("accepted_at"),
        "receipts": [
            {"id": r.id, "created_at": r.created_at.isoformat()} for r in receipts
        ],
        "grants": [
            {
                "consumed": g.consumed_at is not None,
                "expires_at": g.expires_at.isoformat(),
            }
            for g in grants
        ],
        "send_calls_logged": len(attempts),
        "result": state.get("result") or None,
    }


@router.get("/runs/{run_id}/events")
async def events(
    run_id: str,
    request: Request,
    user=Depends(authenticated),
    service=Depends(coordinator),
):
    run = await owned(service, user.subject, run_id)

    async def stream():
        seen = set()
        while not await request.is_disconnected():
            async with service.sessions() as session:
                records = (
                    await session.scalars(
                        select(AuditLog)
                        .where(
                            AuditLog.user_id == user.subject,
                            AuditLog.trace_id == run.trace_id,
                        )
                        .order_by(AuditLog.created_at, AuditLog.id)
                    )
                ).all()
                for record in records:
                    if record.id not in seen:
                        seen.add(record.id)
                        yield (
                            "data: "
                            + json.dumps(
                                {
                                    "id": record.id,
                                    "action": record.action,
                                    "payload": record.payload,
                                }
                            )
                            + "\n\n"
                        )
                current = await session.get(GraphRun, run_id)
                yield (
                    "event: status\ndata: "
                    + json.dumps({"status": current.status})
                    + "\n\n"
                )
            await asyncio.sleep(2)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/memory/style/recent")
async def recent_style_edits(
    user=Depends(authenticated), service=Depends(coordinator)
) -> dict:
    """The last five deletions style memory observed and why each was or was not promoted."""
    from agent.memory.promotion_rules import PROMOTION_RULE, PROMOTION_THRESHOLD

    observations = await service.store.asearch(
        (user.subject, "style_observations"), limit=1000
    )
    promoted = {
        item.key
        for item in await service.store.asearch((user.subject, "style"), limit=1000)
    }
    threads: dict[str, set[str]] = {}
    for item in observations:
        threads.setdefault(item.value["pattern"], set()).add(item.value["thread_id"])
    latest = sorted(observations, key=lambda item: item.updated_at, reverse=True)[:5]
    return {
        "rule": PROMOTION_RULE,
        "threshold": PROMOTION_THRESHOLD,
        "edits": [
            {
                "removed_sentence": item.value["removed_sentence"],
                "run_id": item.value["thread_id"],
                "key": item.value["pattern"],
                "seen_in_proposals": len(threads[item.value["pattern"]]),
                "promoted": item.value["pattern"] in promoted,
            }
            for item in latest
        ],
        "note": "Only whole sentences you deleted from the cover letter are observed. "
        "Rewording, additions and sentences containing personal data are not learned.",
    }


@router.get("/memory/{kind}")
async def memories(
    kind: Literal["style", "outcome"],
    user=Depends(authenticated),
    service=Depends(coordinator),
) -> list[dict]:
    return [
        {"key": item.key, "value": item.value}
        for item in await service.store.asearch((user.subject, kind), limit=100)
    ]


@router.delete("/memory/{kind}/{key}", status_code=204)
async def forget(
    kind: Literal["style", "outcome"],
    key: str,
    user=Depends(authenticated),
    service=Depends(coordinator),
):
    await service.store.adelete((user.subject, kind), key)
    if kind == "style":
        for item in await service.store.asearch(
            (user.subject, "style_observations"), filter={"pattern": key}, limit=1000
        ):
            await service.store.adelete(item.namespace, item.key)


def checked_evidence_id(item_id: str, user) -> str:
    persona = user.claims["persona"]
    if (
        not item_id.startswith(persona + ":")
        or ".." in item_id
        or "\\" in item_id
        or len(item_id) > 250
    ):
        raise HTTPException(404, "Evidence item not found")
    return item_id


@router.get("/evidence/retired")
async def retired_evidence(request: Request, user=Depends(authenticated)) -> list[str]:
    async with async_sessionmaker(request.app.state.engine)() as session:
        return list(
            await session.scalars(
                select(RetiredEvidence.item_id).where(
                    RetiredEvidence.user_id == user.subject
                )
            )
        )


@router.delete("/evidence/{item_id:path}", status_code=204)
async def retire_evidence(
    item_id: str, request: Request, user=Depends(authenticated)
):
    """Remove an evidence item from retrieval and verification for this user."""
    item_id = checked_evidence_id(item_id, user)
    async with async_sessionmaker(request.app.state.engine)() as session, session.begin():
        exists = await session.scalar(
            select(RetiredEvidence.id).where(
                RetiredEvidence.user_id == user.subject,
                RetiredEvidence.item_id == item_id,
            )
        )
        if exists is None:
            session.add(RetiredEvidence(user_id=user.subject, item_id=item_id))
        session.add(
            AuditLog(
                user_id=user.subject,
                trace_id="evidence:" + uuid.uuid4().hex,
                action="human.retire_evidence",
                payload={"item_id": item_id},
            )
        )


@router.post("/evidence/restore/{item_id:path}", status_code=204)
async def restore_evidence(
    item_id: str, request: Request, user=Depends(authenticated)
):
    item_id = checked_evidence_id(item_id, user)
    async with async_sessionmaker(request.app.state.engine)() as session, session.begin():
        row = await session.scalar(
            select(RetiredEvidence).where(
                RetiredEvidence.user_id == user.subject,
                RetiredEvidence.item_id == item_id,
            )
        )
        if row is not None:
            await session.delete(row)
        session.add(
            AuditLog(
                user_id=user.subject,
                trace_id="evidence:" + uuid.uuid4().hex,
                action="human.restore_evidence",
                payload={"item_id": item_id},
            )
        )


@router.post("/runs/{run_id}/outcome")
async def outcome(
    run_id: str, user=Depends(authenticated), service=Depends(coordinator)
) -> dict:
    run = await owned(service, user.subject, run_id)
    state = (await service.snapshot(run)).values
    if run.kind != "bid" or run.status != "sent" or not state.get("result"):
        raise HTTPException(409, "A sent proposal is required")
    port = MCPMarketplacePort(MCPGateway(user.token, "risk", run.trace_id))
    history = await port.get_client_history(state["job"]["client_id"])
    async with service.sessions() as session:
        owner = await session.get(User, user.subject)
    confirmed = [
        p
        for p in history.past_proposals
        if p.job_id == run.target and p.freelancer_id == owner.persona
    ]
    if not confirmed:
        raise HTTPException(409, "No matching marketplace outcome")
    promoted = await promote_outcome(
        service.store,
        user.subject,
        run.id,
        state["job"].get("category"),
        confirmed[0].status,
        {"confirmed": True},
    )
    return {"promoted": promoted, "outcome": confirmed[0].status}
