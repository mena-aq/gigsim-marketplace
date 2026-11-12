"""Admin endpoints: stream-job release, ground truth labels and stats.

The admin token is separate from freelancer tokens; POST /admin/stream is meant to be
called by the GigBid worker.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gigsim.auth import require_admin
from gigsim.db import get_session
from gigsim.models import AuditLog, Client, Job, Message, Proposal
from gigsim.schemas import AdminStats, JobGroundTruth, StreamRelease
from gigsim.util import utcnow

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.post("/stream", response_model=StreamRelease)
async def release_stream_jobs(
    request: Request,
    count: int = Query(default=1, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
) -> StreamRelease:
    jobs = (
        await session.execute(
            select(Job)
            .where(Job.status == "pending")
            .order_by(Job.posted_at.nullslast())
            .limit(count)
        )
    ).scalars().all()
    now = utcnow()
    for job in jobs:
        job.status = "open"
        job.posted_at = now
    remaining = (
        await session.execute(select(func.count(Job.id)).where(Job.status == "pending"))
    ).scalar_one()
    if jobs:
        session.add(
            AuditLog(
                freelancer_id="admin",
                action="admin_stream",
                payload={"released": [job.id for job in jobs], "remaining": remaining},
            )
        )
    await session.commit()
    return StreamRelease(released=[job.id for job in jobs], remaining=remaining)


@router.get("/jobs/{job_id}", response_model=JobGroundTruth)
async def job_ground_truth(job_id: str, session: AsyncSession = Depends(get_session)) -> JobGroundTruth:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobGroundTruth.model_validate(job, from_attributes=True)


@router.get("/stats", response_model=AdminStats)
async def stats(session: AsyncSession = Depends(get_session)) -> AdminStats:
    async def count(stmt) -> int:
        return (await session.execute(stmt)).scalar_one()

    return AdminStats(
        jobs_total=await count(select(func.count(Job.id))),
        jobs_open=await count(select(func.count(Job.id)).where(Job.status == "open")),
        jobs_pending=await count(select(func.count(Job.id)).where(Job.status == "pending")),
        jobs_filled=await count(select(func.count(Job.id)).where(Job.status == "filled")),
        scams=await count(select(func.count(Job.id)).where(Job.is_scam.is_(True))),
        injections=await count(select(func.count(Job.id)).where(Job.has_injection.is_(True))),
        clients=await count(select(func.count(Client.id))),
        bad_actors=await count(select(func.count(Client.id)).where(Client.is_bad_actor.is_(True))),
        proposals=await count(select(func.count(Proposal.id))),
        messages=await count(select(func.count(Message.id))),
    )
