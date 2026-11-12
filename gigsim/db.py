"""Database engine/session helpers for GigSim."""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool


def build_engine(database_url: str) -> AsyncEngine:
    if database_url.startswith("sqlite"):
        pool_kwargs = {}
        if database_url in ("sqlite+aiosqlite://", "sqlite+aiosqlite:///:memory:"):
            pool_kwargs = {"poolclass": StaticPool}
        return create_async_engine(
            database_url, connect_args={"check_same_thread": False}, **pool_kwargs
        )
    return create_async_engine(database_url, pool_pre_ping=True)


def build_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


async def init_db(engine: AsyncEngine) -> None:
    from gigsim.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
