"""Delayed client reply simulation, executed as a background task."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gigsim import reply_sim
from gigsim.models import AuditLog, Client, Job, Message, Proposal
from gigsim.util import utcnow


async def run_reply_simulation(
    sessionmaker: async_sessionmaker[AsyncSession], proposal_id: int
) -> None:
    """Apply the rule-based reply simulator to one submitted proposal."""
    async with sessionmaker() as session:
        proposal = await session.get(Proposal, proposal_id)
        if proposal is None or proposal.status != "submitted":
            return
        job = await session.get(Job, proposal.job_id)
        client = await session.get(Client, job.client_id) if job and job.client_id else None
        if client is None:
            proposal.status = "no_reply"
            await session.commit()
            return

        outcome = reply_sim.simulate_reply(
            client.hire_rate,
            client.hidden_preferences or {},
            proposal.cover_letter,
            proposal.skills_mentioned or [],
        )
        proposal.status = outcome
        if outcome in ("replied", "interview", "hired"):
            body = reply_sim.client_message(outcome, client.name, job.title)
            if body:
                session.add(
                    Message(
                        conversation_id=proposal.conversation_id,
                        sender="client",
                        body=body,
                        sent_at=utcnow(),
                    )
                )
        if outcome == "hired":
            job.status = "filled"

        session.add(
            AuditLog(
                freelancer_id=proposal.freelancer_id,
                action="reply_simulated",
                payload={"proposal_id": proposal.id, "outcome": outcome},
            )
        )
        await session.commit()
