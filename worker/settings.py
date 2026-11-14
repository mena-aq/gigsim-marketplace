"""Arq entry point. Scouting and graph jobs will be added in later milestones."""

import os
from typing import Any

from arq import cron
from arq.connections import RedisSettings
from arq.worker import func
from sqlalchemy import select

from agent.persistence import graph_storage
from agent.runs import RunCoordinator
from apps.api.config import Settings
from apps.api.db import build_engine
from apps.api.models import GraphRun


async def smoke_task(ctx: dict[str, Any], token: str) -> dict[str, str]:
    """Return a receipt proving a separate worker consumed the job."""
    return {"token": token, "worker_pid": str(os.getpid())}


async def startup(ctx):
    from mcp_servers.common.security import install_log_redaction

    install_log_redaction()
    ctx["engine"] = build_engine(Settings().database_url)
    ctx["storage"] = graph_storage(Settings().database_url)
    saver, store = await ctx["storage"].__aenter__()
    ctx["runs"] = RunCoordinator(ctx["engine"], saver, store)


async def shutdown(ctx):
    await ctx["storage"].__aexit__(None, None, None)
    await ctx["engine"].dispose()


async def process_graph(ctx, run_id):
    await ctx["runs"].process(run_id)


async def recover_graphs(ctx):
    """Database outbox survives Redis loss and API/worker crashes."""
    from datetime import UTC, datetime

    async with ctx["runs"].sessions() as session:
        runs = (
            await session.scalars(
                select(GraphRun)
                .where(GraphRun.status.in_(["queued", "running", "retry_wait"]))
                .order_by(GraphRun.created_at)
                .limit(100)
            )
        ).all()
    for run in runs:
        if run.retry_at is None or run.retry_at <= datetime.now(UTC):
            await ctx["redis"].enqueue_job(
                "process_graph", run.id, _job_id="graph:" + run.id
            )


class WorkerSettings:
    functions = (smoke_task, func(process_graph, keep_result=0))
    cron_jobs = (
        cron(recover_graphs, second=set(range(0, 60, 10)), run_at_startup=True),
    )
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(Settings().redis_url)
    health_check_interval = 10
    job_timeout = 7200
    max_jobs = 3
    max_tries = 2
    keep_result = 60
