"""Seed a few already-submitted proposals with client conversations into GigSim.

Usage:  python -m scripts.seed_demo_chats [--per-freelancer N] [--database-url URL]
                                    [--replace-demo]

Jobs are chosen to fit each persona's skills (agent.job_match), so a conversation
is about work that persona would really bid on. For each freelancer persona this
inserts a few submitted proposals (no Connects are
spent), then runs GigSim's own reply simulator on each one immediately instead of
waiting for its 5-30 s scheduler delay. The simulator sometimes decides "no reply";
when that happens a fixed client message is added so every demo conversation has a
client message. The output says which conversations were simulated and which were
filled in. Idempotent: re-running adds nothing that already exists.

GigSim itself is not modified; this script only uses its models and reply runner.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import delete, select

from agent.config import load_graph_config
from agent.job_match import below_floor, rank_jobs
from gigsim import reply_sim
from gigsim.config import Settings
from gigsim.db import build_engine, build_sessionmaker, init_db
from gigsim.models import Client, Job, Message, Proposal
from gigsim.reply_runner import run_reply_simulation
from gigsim.util import utcnow

KEY = "demo-chat:{job}:{freelancer}"
PERSONAS_DIR = Path(__file__).resolve().parents[1] / "data" / "personas"


def load_persona_skills(freelancers) -> dict[str, list[str]]:
    skills = {}
    for freelancer_id in freelancers:
        path = PERSONAS_DIR / freelancer_id / "skills.json"
        skills[freelancer_id] = json.loads(path.read_text())["skills"] if path.exists() else []
    return skills


async def remove_demo_chats(sessionmaker) -> int:
    """Delete earlier demo proposals and their client messages, but never a
    conversation where the freelancer has already sent something."""
    removed = 0
    async with sessionmaker() as session:
        demos = (
            await session.execute(
                select(Proposal).where(Proposal.idempotency_key.like("demo-chat:%"))
            )
        ).scalars().all()
        for proposal in demos:
            mine = await session.scalar(
                select(Message.id).where(
                    Message.conversation_id == proposal.conversation_id,
                    Message.sender == "freelancer",
                )
            )
            if mine is not None:
                continue
            await session.execute(
                delete(Message).where(Message.conversation_id == proposal.conversation_id)
            )
            await session.delete(proposal)
            removed += 1
        await session.commit()
    return removed


def cover_letter(job: Job) -> str:
    skills = ", ".join(job.skills[:3]) if job.skills else "the skills you listed"
    return (
        f"I read your post for {job.title} and would approach it in small, checkable "
        f"steps. I have worked with {skills}, so I can start on the first milestone "
        "this week and share progress as I go."
    )


async def seed_demo_chats(
    settings: Settings,
    per_freelancer: int = 3,
    skills_by_persona: dict[str, list[str]] | None = None,
    replace_demo: bool = False,
) -> dict:
    engine = build_engine(settings.database_url)
    sessionmaker = build_sessionmaker(engine)
    await init_db(engine)
    created = {"simulated": [], "fallback": [], "existing": [], "removed": 0}
    if replace_demo:
        created["removed"] = await remove_demo_chats(sessionmaker)

    async with sessionmaker() as session:
        jobs = (
            await session.execute(select(Job).where(Job.status == "open"))
        ).scalars().all()
        clients = {
            client.id: client
            for client in (await session.execute(select(Client))).scalars().all()
        }
    unsafe = {
        client.id
        for client in clients.values()
        if client.is_bad_actor or client.hire_rate < 0.1
    }
    by_id = {job.id: job for job in jobs}
    records = [
        {
            "id": job.id,
            "title": job.title,
            "description": job.description,
            "skills": list(job.skills or []),
            "category": job.category,
            "budget_max": job.budget_max,
            "client_id": job.client_id,
            "is_scam": job.is_scam,
            "has_injection": job.has_injection,
        }
        for job in jobs
    ]

    floor = load_graph_config()["orchestration"]["minimum_price"]

    def exclude(record: dict) -> bool:
        return (
            below_floor(record, floor)
            or
            record["is_scam"]
            or record["has_injection"]
            or record["client_id"] not in clients
            or record["client_id"] in unsafe
        )

    freelancers = list(settings.freelancer_tokens)
    skills_by_persona = skills_by_persona or load_persona_skills(freelancers)
    for freelancer_id in freelancers:
        ranked = rank_jobs(
            skills_by_persona.get(freelancer_id, []),
            records,
            exclude=exclude,
            limit=per_freelancer,
        )
        picks = [
            (by_id[item["job"]["id"]], clients[item["job"]["client_id"]])
            for item in ranked
        ]
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
    parser.add_argument(
        "--replace-demo",
        action="store_true",
        help="first remove earlier demo chats (never ones you have replied to)",
    )
    args = parser.parse_args()
    settings = (
        Settings(database_url=args.database_url, _env_file=None)
        if args.database_url
        else Settings()
    )
    result = asyncio.run(seed_demo_chats(settings, args.per_freelancer, replace_demo=args.replace_demo))
    print(
        f"[demo-chats] {len(result['simulated'])} from GigSim's simulator, "
        f"{len(result['fallback'])} filled in with a fixed message, "
        f"{len(result['existing'])} already present"
        + (f", {result['removed']} older demo chats removed" if args.replace_demo else "")
    )
    for label in ("simulated", "fallback"):
        for conversation_id in result[label]:
            print(f"  {label}: {conversation_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
