"""Seed a few already-submitted proposals with client conversations into GigSim.

Usage:  python -m scripts.seed_demo_chats [--per-freelancer N] [--database-url URL]

For each freelancer persona this inserts a few submitted proposals (no Connects are
spent), then runs GigSim's own reply simulator on each one immediately instead of
waiting for its 5-30 s scheduler delay. The simulator sometimes decides "no reply";
when that happens a fixed client message is added so every demo conversation has a
client message. The output says which conversations were simulated and which were
filled in. Idempotent: re-running adds nothing that already exists.

GigSim itself is not modified; this script only uses its models and reply runner.
"""

import argparse
import asyncio
import sys

from sqlalchemy import select

from gigsim import reply_sim
from gigsim.config import Settings
from gigsim.db import build_engine, build_sessionmaker, init_db
from gigsim.models import Client, Job, Message, Proposal
from gigsim.reply_runner import run_reply_simulation
from gigsim.util import utcnow

KEY = "demo-chat:{job}:{freelancer}"


def cover_letter(job: Job) -> str:
    skills = ", ".join(job.skills[:3]) if job.skills else "the skills you listed"
    return (
        f"I read your post for {job.title} and would approach it in small, checkable "
        f"steps. I have worked with {skills}, so I can start on the first milestone "
        "this week and share progress as I go."
    )


async def seed_demo_chats(settings: Settings, per_freelancer: int = 3) -> dict:
    engine = build_engine(settings.database_url)
    sessionmaker = build_sessionmaker(engine)
    await init_db(engine)
    created = {"simulated": [], "fallback": [], "existing": []}

    async with sessionmaker() as session:
        rows = (
            await session.execute(
                select(Job, Client)
                .join(Client, Client.id == Job.client_id)
                .where(
                    Job.status == "open",
                    Job.is_scam.is_(False),
                    Job.has_injection.is_(False),
                    Client.is_bad_actor.is_(False),
                    Client.hire_rate >= 0.1,
                )
                .order_by(Job.id)
            )
        ).all()

    freelancers = list(settings.freelancer_tokens)
    for index, freelancer_id in enumerate(freelancers):
        # Each persona gets its own slice so the demo conversations differ.
        picks = rows[index * per_freelancer : (index + 1) * per_freelancer]
        for job, client in picks:
            key = KEY.format(job=job.id, freelancer=freelancer_id)
            conversation_id = f"{job.id}:{freelancer_id}"
            async with sessionmaker() as session:
                found = await session.scalar(
                    select(Proposal).where(
                        Proposal.freelancer_id == freelancer_id,
                        Proposal.idempotency_key == key,
                    )
                )
                if found is not None:
                    created["existing"].append(conversation_id)
                    continue
                proposal = Proposal(
                    job_id=job.id,
                    freelancer_id=freelancer_id,
                    cover_letter=cover_letter(job),
                    skills_mentioned=list(job.skills or []),
                    screening_answers=[],
                    status="submitted",
                    connects_spent=0,
                    idempotency_key=key,
                    conversation_id=conversation_id,
                    submitted_at=utcnow(),
                )
                session.add(proposal)
                await session.commit()
                proposal_id = proposal.id

            # GigSim's own simulator decides the outcome and writes the client message.
            await run_reply_simulation(sessionmaker, proposal_id)

            async with sessionmaker() as session:
                proposal = await session.get(Proposal, proposal_id)
                stored_job = await session.get(Job, job.id)
                if proposal.status == "hired":
                    # Keep demo jobs open: a hired reply would fill the job and hide
                    # it from the inbox. Treat it as an interview instead.
                    proposal.status = "interview"
                    stored_job.status = "open"
                has_message = await session.scalar(
                    select(Message.id).where(Message.conversation_id == conversation_id)
                )
                if has_message is None:
                    proposal.status = "replied"
                    session.add(
                        Message(
                            conversation_id=conversation_id,
                            sender="client",
                            body=reply_sim.client_message(
                                "replied", client.name, job.title
                            ),
                            sent_at=utcnow(),
                        )
                    )
                    created["fallback"].append(conversation_id)
                else:
                    created["simulated"].append(conversation_id)
                await session.commit()

    await engine.dispose()
    return created


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--per-freelancer", type=int, default=3)
    parser.add_argument("--database-url", default=None, help="override GIGSIM_DATABASE_URL")
    args = parser.parse_args()
    settings = (
        Settings(database_url=args.database_url, _env_file=None)
        if args.database_url
        else Settings()
    )
    result = asyncio.run(seed_demo_chats(settings, args.per_freelancer))
    print(
        f"[demo-chats] {len(result['simulated'])} from GigSim's simulator, "
        f"{len(result['fallback'])} filled in with a fixed message, "
        f"{len(result['existing'])} already present"
    )
    for label in ("simulated", "fallback"):
        for conversation_id in result[label]:
            print(f"  {label}: {conversation_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
