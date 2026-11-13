"""Arq entry point. Scouting and graph jobs will be added in later milestones."""

import os
from typing import Any

from arq.connections import RedisSettings

from apps.api.config import Settings


async def smoke_task(ctx: dict[str, Any], token: str) -> dict[str, str]:
    """Return a receipt proving a separate worker consumed the job."""
    return {"token": token, "worker_pid": str(os.getpid())}


class WorkerSettings:
    functions = (smoke_task,)
    redis_settings = RedisSettings.from_dsn(Settings().redis_url)
    health_check_interval = 10
    job_timeout = 30
    max_tries = 2
    keep_result = 60
