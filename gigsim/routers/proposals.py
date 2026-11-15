"""Proposal submission with idempotency, Connects accounting and reply scheduling."""

import random

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gigsim.auth import get_current_freelancer
from gigsim.db import get_session
from gigsim.idempotency import remember, replay, write_lock
from gigsim.models import AuditLog, Connects, Job, Proposal
from gigsim.reply_runner import run_reply_simulation
from gigsim.scheduler import schedule
from gigsim.schemas import ProposalIn, ProposalOut
from gigsim.util import utcnow

router = APIRouter(prefix="/proposals", tags=["proposals"], dependencies=[Depends(get_current_freelancer)])


def connects_cost(job: Job, settings) -> int:
    budget = job.budget_max if job.budget_max is not None else job.budget_min
    if budget is not None and budget >= settings.connects_high_budget_threshold:
        return settings.connects_cost_high
    return settings.connects_cost_low


async def get_or_create_connects(
    session: AsyncSession, freelancer_id: str, initial: int
) -> Connects:
    connects = await session.get(Connects, freelancer_id)
    if connects is None:
        connects = Connects(freelancer_id=freelancer_id, balance=initial)
        session.add(connects)
        await session.flush()
    return connects


@router.post("", response_model=ProposalOut, status_code=201)
async def submit_proposal(
    payload: ProposalIn,
    request: Request,
    freelancer_id: str = Depends(get_current_freelancer),
    session: AsyncSession = Depends(get_session),
) -> ProposalOut:
    async with write_lock(session, freelancer_id):
        return await _submit_proposal(payload, request, freelancer_id, session)


async def _submit_proposal(
    payload: ProposalIn, request: Request, freelancer_id: str, session: AsyncSession
) -> ProposalOut:
    if not payload.dry_run:
        receipt = await replay(
            session, freelancer_id, "submit_proposal", payload.idempotency_key, payload
        )
        if receipt is not None:
            return ProposalOut.model_validate({**receipt, "idempotent_replay": True})
    settings = request.app.state.settings

    existing = (
        await session.execute(
            select(Proposal).where(
                Proposal.freelancer_id == freelancer_id,
                Proposal.idempotency_key == payload.idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if (
            existing.job_id != payload.job_id
            or existing.cover_letter != payload.cover_letter
            or existing.screening_answers != payload.screening_answers
            or (payload.skills_mentioned and existing.skills_mentioned != payload.skills_mentioned)
        ):
            raise HTTPException(status_code=409, detail="Idempotency key belongs to different arguments")
        connects = await session.get(Connects, freelancer_id)
        result = ProposalOut.model_validate(existing, from_attributes=True)
        result.idempotent_replay = True
        result.connects_remaining = connects.balance if connects else None
        return result

    job = await session.get(Job, payload.job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "open":
        raise HTTPException(status_code=409, detail="Job is not open for proposals")

    skills_mentioned = payload.skills_mentioned
    if not skills_mentioned:
        cover = payload.cover_letter.lower()
        skills_mentioned = [s for s in (job.skills or []) if s.lower() in cover]

    cost = connects_cost(job, settings)
    connects = await get_or_create_connects(session, freelancer_id, settings.initial_connects)
    if connects.balance < cost:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "insufficient_connects",
                "balance": connects.balance,
                "required": cost,
            },
        )

    if payload.dry_run:
        remaining = connects.balance - cost
        conversation_id = f"{job.id}:{freelancer_id}"
        job_id = job.id
        await session.rollback()
        return ProposalOut(
            id=0,
            job_id=job_id,
            freelancer_id=freelancer_id,
            status="dry_run",
            connects_spent=cost,
            conversation_id=conversation_id,
            submitted_at=utcnow(),
            connects_remaining=remaining,
        )

    conversation_id = f"{job.id}:{freelancer_id}"
    proposal = Proposal(
        job_id=job.id,
        freelancer_id=freelancer_id,
        cover_letter=payload.cover_letter,
        skills_mentioned=skills_mentioned,
        screening_answers=payload.screening_answers,
        idempotency_key=payload.idempotency_key,
        conversation_id=conversation_id,
        connects_spent=cost,
        status="submitted",
        submitted_at=utcnow(),
    )
    session.add(proposal)
    connects.balance -= cost
    session.add(
        AuditLog(
            freelancer_id=freelancer_id,
            action="proposal_submitted",
            payload={
                "job_id": job.id,
                "idempotency_key": payload.idempotency_key,
                "connects_spent": cost,
            },
        )
    )
    await session.flush()

    delay = random.uniform(
        settings.reply_delay_min_seconds, settings.reply_delay_max_seconds
    )
    result = ProposalOut.model_validate(proposal, from_attributes=True)
    result.connects_remaining = connects.balance
    remember(
        session, freelancer_id, "submit_proposal", payload.idempotency_key, payload, result
    )
    await session.commit()
    schedule(run_reply_simulation(request.app.state.sessionmaker, proposal.id), delay)
    return result


@router.get("", response_model=list[ProposalOut])
async def list_own_proposals(
    job_id: str | None = None,
    freelancer_id: str = Depends(get_current_freelancer),
    session: AsyncSession = Depends(get_session),
) -> list[ProposalOut]:
    stmt = select(Proposal).where(Proposal.freelancer_id == freelancer_id)
    if job_id:
        stmt = stmt.where(Proposal.job_id == job_id)
    proposals = (await session.execute(stmt.order_by(Proposal.submitted_at.desc()))).scalars().all()
    return [ProposalOut.model_validate(p, from_attributes=True) for p in proposals]
