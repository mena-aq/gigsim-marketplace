"""Job search and detail endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from gigsim.auth import get_current_freelancer
from gigsim.db import get_session
from gigsim.models import Job
from gigsim.schemas import JobOut, JobPage

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Depends(get_current_freelancer)])


@router.get("", response_model=JobPage)
async def list_jobs(
    q: str | None = None,
    category: str | None = None,
    budget_min: float | None = Query(default=None, ge=0),
    budget_max: float | None = Query(default=None, ge=0),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> JobPage:
    stmt = select(Job).where(Job.status == "open")
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Job.title.ilike(like), Job.description.ilike(like)))
    if category:
        stmt = stmt.where(func.lower(Job.category) == category.strip().lower())
    if budget_min is not None:
        stmt = stmt.where(Job.budget_max >= budget_min)
    if budget_max is not None:
        stmt = stmt.where(Job.budget_min <= budget_max)

    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    items = (
        (
            await session.execute(
                stmt.order_by(Job.posted_at.desc().nullslast()).offset((page - 1) * page_size).limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return JobPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: str, session: AsyncSession = Depends(get_session)) -> JobOut:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobOut.model_validate(job)
