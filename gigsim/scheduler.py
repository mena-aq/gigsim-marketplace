"""In-process background task scheduler for the delayed client replies."""

import asyncio

_tasks: set[asyncio.Task] = set()


def schedule(coro, delay: float) -> asyncio.Task:
    async def runner() -> None:
        try:
            await asyncio.sleep(delay)
            await coro
        except Exception as exc:  # noqa: BLE001 - background tasks must never crash the app
            print(f"[gigsim] background task failed: {exc}")
        finally:
            try:
                coro.close()
            except RuntimeError:
                pass

    task = asyncio.create_task(runner())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


async def wait_all() -> None:
    """Wait until every scheduled task has finished (used by tests)."""
    while _tasks:
        await asyncio.gather(*list(_tasks))


def cancel_all() -> int:
    """Cancel pending tasks (test teardown); returns how many were pending."""
    tasks = list(_tasks)
    for task in tasks:
        task.cancel()
    return len(tasks)
