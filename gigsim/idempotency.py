"""Durable simulator write receipts and per-freelancer transaction locking."""

import asyncio
import hashlib
import json
import weakref
from contextlib import asynccontextmanager

from fastapi import HTTPException
from sqlalchemy import select, text

from gigsim.models import WriteReceipt

_LOCAL_LOCKS = weakref.WeakKeyDictionary()


@asynccontextmanager
async def write_lock(session, freelancer_id):
    if session.bind.dialect.name == "postgresql":
        key = int.from_bytes(
            hashlib.sha256(freelancer_id.encode()).digest()[:8], "big", signed=True
        )
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
        yield
    else:
        locks = _LOCAL_LOCKS.setdefault(asyncio.get_running_loop(), {})
        async with locks.setdefault(freelancer_id, asyncio.Lock()):
            yield


def payload_hash(payload):
    data = payload.model_dump(mode="json", exclude={"dry_run"})
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def replay(session, freelancer_id, operation, key, payload):
    receipt = (
        await session.execute(
            select(WriteReceipt).where(
                WriteReceipt.freelancer_id == freelancer_id,
                WriteReceipt.operation == operation,
                WriteReceipt.idempotency_key == key,
            )
        )
    ).scalar_one_or_none()
    if receipt is None:
        return None
    if receipt.payload_hash != payload_hash(payload):
        raise HTTPException(
            status_code=409, detail="Idempotency key belongs to different arguments"
        )
    return receipt.response


def remember(session, freelancer_id, operation, key, payload, response):
    session.add(
        WriteReceipt(
            freelancer_id=freelancer_id,
            operation=operation,
            idempotency_key=key,
            payload_hash=payload_hash(payload),
            response=response.model_dump(mode="json"),
        )
    )
