"""Connects balance endpoint."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from gigsim.auth import get_current_freelancer
from gigsim.db import get_session
from gigsim.routers.proposals import get_or_create_connects
from gigsim.schemas import ConnectsOut

router = APIRouter(tags=["connects"], dependencies=[Depends(get_current_freelancer)])


@router.get("/connects", response_model=ConnectsOut)
async def get_connects(
    request: Request,
    freelancer_id: str = Depends(get_current_freelancer),
    session: AsyncSession = Depends(get_session),
) -> ConnectsOut:
    connects = await get_or_create_connects(
        session, freelancer_id, request.app.state.settings.initial_connects
    )
    await session.commit()
    return ConnectsOut(freelancer_id=freelancer_id, balance=connects.balance)
