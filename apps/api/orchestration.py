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
from apps.api.models import AuditLog, GraphRun, User
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
        raise HTTPException(404, "Job not found or marketplace unavailable") from exc


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
    async with async_sessionmaker(request.app.state.engine)() as session:
        rows = (
            await session.scalars(
                select(GraphRun)
                .where(GraphRun.user_id == user.subject)
                .order_by(GraphRun.created_at.desc())
                .limit(100)
            )
        ).all()
        return [summary(row) for row in rows]


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
