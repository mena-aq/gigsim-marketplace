"""Client history endpoint (public marketplace info only, never hidden preferences)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gigsim.auth import get_current_freelancer
from gigsim.db import get_session
from gigsim.models import Client, Job, Proposal
from gigsim.schemas import ClientHistory, ClientHistoryProposal, ClientOut

router = APIRouter(
    prefix="/clients", tags=["clients"], dependencies=[Depends(get_current_freelancer)]
)


@router.get("/{client_id}/history", response_model=ClientHistory)
async def client_history(client_id: str, session: AsyncSession = Depends(get_session)) -> ClientHistory:
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    stmt = (
        select(Proposal, Job.title)
        .join(Job, Proposal.job_id == Job.id)
        .where(Job.client_id == client_id)
        .order_by(Proposal.submitted_at.desc())
        .limit(50)
    )
    rows = (await session.execute(stmt)).all()
    total = (
        await session.execute(
            select(func.count(Proposal.id))
            .join(Job, Proposal.job_id == Job.id)
            .where(Job.client_id == client_id)
        )
    ).scalar_one()

    return ClientHistory(
        client=ClientOut.model_validate(client),
        proposals_received=total,
        past_proposals=[
            ClientHistoryProposal(
                job_id=proposal.job_id,
                job_title=job_title or proposal.job_id,
                freelancer_id=proposal.freelancer_id,
                status=proposal.status,
                connects_spent=proposal.connects_spent,
                submitted_at=proposal.submitted_at,
            )
            for proposal, job_title in rows
        ],
        reviews=list(client.reviews or []),
    )
