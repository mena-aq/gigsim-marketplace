"""Conversation messages: list a thread, list threads, and send freelancer messages."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gigsim.auth import get_current_freelancer
from gigsim.db import get_session
from gigsim.idempotency import remember, replay, write_lock
from gigsim.models import AuditLog, Message, Proposal
from gigsim.schemas import ConversationSummary, MessageIn, MessageOut
from gigsim.util import utcnow

router = APIRouter(prefix="/messages", tags=["messages"], dependencies=[Depends(get_current_freelancer)])


def _owns(conversation_id: str, freelancer_id: str) -> bool:
    return conversation_id.endswith(f":{freelancer_id}")


@router.get("", response_model=list[MessageOut])
async def list_messages(
    conversation_id: str,
    freelancer_id: str = Depends(get_current_freelancer),
    session: AsyncSession = Depends(get_session),
) -> list[MessageOut]:
    if not _owns(conversation_id, freelancer_id):
        raise HTTPException(status_code=403, detail="Not your conversation")
    exists = (
        await session.execute(select(Proposal).where(Proposal.conversation_id == conversation_id))
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = (
        await session.execute(
            select(Message).where(Message.conversation_id == conversation_id).order_by(Message.sent_at)
        )
    ).scalars().all()
    return [MessageOut.model_validate(m, from_attributes=True) for m in messages]


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    freelancer_id: str = Depends(get_current_freelancer),
    session: AsyncSession = Depends(get_session),
) -> list[ConversationSummary]:
    proposals = (
        await session.execute(
            select(Proposal)
            .where(Proposal.freelancer_id == freelancer_id)
            .order_by(Proposal.submitted_at.desc())
        )
    ).scalars().all()

    summaries = []
    for proposal in proposals:
        messages = (
            await session.execute(
                select(Message)
                .where(Message.conversation_id == proposal.conversation_id)
                .order_by(Message.sent_at)
            )
        ).scalars().all()
        summaries.append(
            ConversationSummary(
                conversation_id=proposal.conversation_id,
                job_id=proposal.job_id,
                proposal_status=proposal.status,
                last_message=messages[-1].body if messages else None,
                last_message_at=messages[-1].sent_at if messages else None,
                message_count=len(messages),
            )
        )
    return summaries


@router.post("", response_model=MessageOut, status_code=201)
async def send_message(
    payload: MessageIn,
    freelancer_id: str = Depends(get_current_freelancer),
    session: AsyncSession = Depends(get_session),
) -> MessageOut:
    async with write_lock(session, freelancer_id):
        return await _send_message(payload, freelancer_id, session)


async def _send_message(
    payload: MessageIn, freelancer_id: str, session: AsyncSession
) -> MessageOut:
    if payload.idempotency_key and not payload.dry_run:
        existing = await replay(
            session, freelancer_id, "send_message", payload.idempotency_key, payload
        )
        if existing is not None:
            return MessageOut.model_validate(existing)
    if not _owns(payload.conversation_id, freelancer_id):
        raise HTTPException(status_code=403, detail="Not your conversation")
    proposal = (
        await session.execute(
            select(Proposal).where(Proposal.conversation_id == payload.conversation_id)
        )
    ).scalar_one_or_none()
    if proposal is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if payload.dry_run:
        return MessageOut(
            id=0,
            conversation_id=payload.conversation_id,
            sender="freelancer",
            body=payload.body,
            sent_at=utcnow(),
        )

    message = Message(
        conversation_id=payload.conversation_id,
        sender="freelancer",
        body=payload.body,
        sent_at=utcnow(),
    )
    session.add(message)
    session.add(
        AuditLog(
            freelancer_id=freelancer_id,
            action="message_sent",
            payload={"conversation_id": payload.conversation_id},
        )
    )
    await session.flush()
    result = MessageOut.model_validate(message, from_attributes=True)
    if payload.idempotency_key:
        remember(
            session, freelancer_id, "send_message", payload.idempotency_key, payload, result
        )
    await session.commit()
    return result
