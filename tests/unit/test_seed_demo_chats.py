"""The demo-chat seed: simulator first, fixed message only as a fallback."""

import pytest
from sqlalchemy import select

from gigsim import reply_sim
from gigsim.config import Settings
from gigsim.db import build_engine, build_sessionmaker, init_db
from gigsim.models import Client, Connects, Job, Message, Proposal
from scripts.seed_demo_chats import seed_demo_chats


class FixedRng:
    def __init__(self, outcome, roll=1.0):
        self.outcome, self.roll = outcome, roll

    def choices(self, population, weights=None):
        return [self.outcome]

    def random(self):
        return self.roll


@pytest.fixture
async def settings(tmp_path):
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'gigsim.db'}", _env_file=None
    )
    engine = build_engine(settings.database_url)
    await init_db(engine)
    sessionmaker = build_sessionmaker(engine)
    async with sessionmaker() as session:
        session.add(
            Client(
                id="c1",
                name="Northwind Labs",
                hire_rate=0.9,
                hidden_preferences={"must_have_skills": ["python"]},
            )
        )
        session.add(Client(id="bad", name="Scammer", hire_rate=0.9, is_bad_actor=True))
        for number in range(6):
            session.add(
                Job(
                    id=f"job{number}",
                    title=f"Job {number}",
                    description="d",
                    skills=["python"],
                    client_id="c1",
                    status="open",
                )
            )
        session.add(Job(id="job_bad", title="x", description="d", client_id="bad"))
        for freelancer in settings.freelancer_tokens:
            session.add(Connects(freelancer_id=freelancer, balance=60))
        await session.commit()
    await engine.dispose()
    return settings


async def rows(settings, model):
    engine = build_engine(settings.database_url)
    async with build_sessionmaker(engine)() as session:
        result = (await session.execute(select(model))).scalars().all()
    await engine.dispose()
    return result


async def test_seed_is_idempotent_and_spends_no_connects(settings, monkeypatch):
    monkeypatch.setattr(reply_sim, "rng", FixedRng("replied"))
    first = await seed_demo_chats(settings, per_freelancer=2)
    assert len(first["simulated"]) == 6 and not first["fallback"]
    second = await seed_demo_chats(settings, per_freelancer=2)
    assert not second["simulated"] and len(second["existing"]) == 6
    proposals = await rows(settings, Proposal)
    assert len(proposals) == 6
    assert all(p.connects_spent == 0 and p.status == "replied" for p in proposals)
    assert {c.balance for c in await rows(settings, Connects)} == {60}
    # The bad-actor client's job is never used, and conversations differ per persona.
    assert all(p.job_id != "job_bad" for p in proposals)
    assert len({p.job_id for p in proposals}) == 6


async def test_no_reply_from_simulator_falls_back_to_fixed_message(
    settings, monkeypatch
):
    monkeypatch.setattr(reply_sim, "rng", FixedRng("no_reply"))
    result = await seed_demo_chats(settings, per_freelancer=1)
    assert len(result["fallback"]) == 3 and not result["simulated"]
    proposals = await rows(settings, Proposal)
    messages = await rows(settings, Message)
    assert {p.conversation_id for p in proposals} == {
        m.conversation_id for m in messages
    }
    assert all(m.sender == "client" for m in messages)
    assert all(p.status == "replied" for p in proposals)


async def test_hired_reply_does_not_hide_the_job_from_the_inbox(settings, monkeypatch):
    monkeypatch.setattr(reply_sim, "rng", FixedRng("interview", roll=0.0))  # -> hired
    await seed_demo_chats(settings, per_freelancer=1)
    assert all(p.status == "interview" for p in await rows(settings, Proposal))
    assert all(j.status == "open" for j in await rows(settings, Job))
