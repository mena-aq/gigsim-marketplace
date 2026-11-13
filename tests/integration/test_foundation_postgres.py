"""Opt-in tests against an isolated, migrated GigBid Postgres database.

Set FOUNDATION_TEST_DATABASE_URL; never point this at a user database.
Fixtures roll back all test data. Apply migrations before running.
"""

import os
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.models import Job, PipelineCard, Proposal, User

pytestmark = pytest.mark.skipif(
    not os.getenv("FOUNDATION_TEST_DATABASE_URL"),
    reason="requires isolated migrated Postgres",
)


@pytest.fixture
async def session():
    engine = create_async_engine(os.environ["FOUNDATION_TEST_DATABASE_URL"])
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with async_sessionmaker(
            bind=connection, join_transaction_mode="create_savepoint"
        )() as session:
            yield session
        await transaction.rollback()
    await engine.dispose()


async def test_schema_and_constraints(session):
    tables = set(
        (
            await session.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
        ).scalars()
    )
    assert {
        "users",
        "jobs",
        "proposals",
        "messages",
        "pipeline_cards",
        "audit_log",
    } <= tables
    first = User(email="first@example.test")
    second = User(email="second@example.test")
    session.add_all([first, second])
    await session.flush()
    job = Job(
        user_id=first.id,
        marketplace="gigsim",
        external_id="job-1",
        title="Job",
        description="Work",
    )
    session.add(job)
    await session.flush()
    session.add(
        Proposal(
            user_id=first.id,
            job_id=job.id,
            idempotency_key="one",
            cover_letter="Draft",
            price=Decimal("123.45"),
        )
    )
    await session.flush()
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add(
                Proposal(
                    user_id=first.id,
                    job_id=job.id,
                    idempotency_key="one",
                    cover_letter="Duplicate",
                )
            )
            await session.flush()
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add(PipelineCard(user_id=second.id, job_id=job.id))
            await session.flush()
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add(
                Job(
                    user_id=first.id,
                    marketplace="gigsim",
                    external_id="job-1",
                    title="Duplicate",
                    description="Work",
                )
            )
            await session.flush()
    session.add(
        Job(
            user_id=first.id,
            marketplace="upwork",
            external_id="job-1",
            title="Other market",
            description="Work",
        )
    )
    await session.flush()
