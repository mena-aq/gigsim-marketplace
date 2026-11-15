"""Production Postgres checkpointer and long-term store, initialized explicitly."""

from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres import AsyncPostgresStore


def connection_string(url):
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


@asynccontextmanager
async def graph_storage(url):
    dsn = connection_string(url)
    async with (
        AsyncPostgresSaver.from_conn_string(dsn) as saver,
        AsyncPostgresStore.from_conn_string(dsn) as store,
    ):
        yield saver, store


async def setup_storage(url):
    async with graph_storage(url) as (saver, store):
        await saver.setup()
        await store.setup()


if __name__ == "__main__":
    import asyncio

    from apps.api.config import Settings

    asyncio.run(setup_storage(Settings().database_url))
