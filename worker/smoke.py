"""Enqueue a harmless task and wait for the external worker's receipt."""

import asyncio
import uuid

from arq import create_pool
from arq.connections import RedisSettings

from apps.api.config import Settings


async def main() -> None:
    redis = await create_pool(RedisSettings.from_dsn(Settings().redis_url))
    try:
        token = str(uuid.uuid4())
        job = await redis.enqueue_job("smoke_task", token)
        if job is None:
            raise RuntimeError("Smoke task was not enqueued")
        result = await job.result(timeout=30)
        if result["token"] != token:
            raise RuntimeError("Worker returned the wrong receipt")
        print(f"Worker smoke passed (job {job.job_id}, pid {result['worker_pid']})")
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
