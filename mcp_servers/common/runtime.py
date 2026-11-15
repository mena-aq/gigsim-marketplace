"""Shared runtime: audit every executed capability and serialize tenant writes."""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.models import ApprovalGrant, AuditLog, ToolReceipt, User
from mcp_servers.common.config import MCPSettings
from mcp_servers.common.security import (
    TRACE_ID,
    ToolFailure,
    fingerprint,
    identity,
    mask,
)


class Runtime:
    def __init__(
        self,
        settings: MCPSettings | None = None,
        *,
        engine=None,
        redis=None,
        transport=None,
    ):
        self.settings = settings or MCPSettings()
        self.engine = engine or create_async_engine(
            self.settings.database_url, pool_pre_ping=True
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.redis = redis or Redis.from_url(
            self.settings.redis_url, socket_connect_timeout=2, socket_timeout=2
        )
        self.transport = transport

    async def close(self):
        await self.redis.aclose()
        await self.engine.dispose()

    async def run(self, tool, params, callback):
        token = TRACE_ID.set(TRACE_ID.get() or str(uuid.uuid4()))
        try:
            return await self._run(tool, params, callback)
        finally:
            TRACE_ID.reset(token)

    async def _run(self, tool, params, callback):
        trace = TRACE_ID.get()
        who = identity()
        try:
            data = await callback(who)
            result = {"ok": True, "data": data, "error": None, "trace_id": trace}
        except ToolFailure as exc:
            result = {
                "ok": False,
                "data": None,
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "retryable": exc.retryable,
                    "retry_after": exc.retry_after,
                },
                "trace_id": trace,
            }
        except (SQLAlchemyError, RedisError, OSError, KeyError, ValueError, TypeError):
            result = {
                "ok": False,
                "data": None,
                "error": {
                    "code": "dependency_unavailable",
                    "message": "A tool dependency is unavailable or returned invalid data",
                    "retryable": True,
                    "retry_after": None,
                },
                "trace_id": trace,
            }
        # If auditing fails, do not return an unaudited success. Writes still have
        # receipts and upstream idempotency, making recovery safe.
        try:
            async with self.sessions() as session:
                session.add(
                    AuditLog(
                        user_id=who.user_id,
                        action=tool,
                        trace_id=trace,
                        payload=mask({"arguments": params, "result": result}),
                    )
                )
                await session.commit()
        except SQLAlchemyError:
            raise ToolFailure(
                "audit_unavailable",
                "Audit storage unavailable; retry with the same idempotency key",
                True,
            ) from None
        return result

    @asynccontextmanager
    async def tenant_transaction(self, who):
        async with self.sessions() as session, session.begin():
            # One tenant lock also prevents overlapping holds and duplicate writes.
            await session.execute(
                select(User).where(User.id == who.user_id).with_for_update()
            )
            yield session

    async def write(self, who, tool, request, callback, *, approval=False):
        payload = request.model_dump(mode="json", exclude={"dry_run"})
        digest = fingerprint(payload)
        if request.dry_run:
            return await callback(None, True)
        async with self.tenant_transaction(who) as session:
            receipt = (
                await session.execute(
                    select(ToolReceipt).where(
                        ToolReceipt.user_id == who.user_id,
                        ToolReceipt.tool == tool,
                        ToolReceipt.idempotency_key == request.idempotency_key,
                    )
                )
            ).scalar_one_or_none()
            if receipt:
                if receipt.payload_hash != digest:
                    raise ToolFailure(
                        "idempotency_conflict",
                        "This key belongs to different arguments",
                    )
                return receipt.result
            grant = None
            if approval:
                grant = (
                    await session.execute(
                        select(ApprovalGrant)
                        .where(
                            ApprovalGrant.user_id == who.user_id,
                            ApprovalGrant.tool == tool,
                            ApprovalGrant.payload_hash == digest,
                            ApprovalGrant.idempotency_key == request.idempotency_key,
                            ApprovalGrant.consumed_at.is_(None),
                            ApprovalGrant.expires_at > datetime.now(UTC),
                        )
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if grant is None:
                    raise ToolFailure(
                        "approval_required",
                        "Approve this exact action in the future approval UI before sending",
                    )
            result = await callback(session, False)
            session.add(
                ToolReceipt(
                    user_id=who.user_id,
                    tool=tool,
                    idempotency_key=request.idempotency_key,
                    payload_hash=digest,
                    result=result,
                )
            )
            if grant is not None:
                grant.consumed_at = datetime.now(UTC)
            return result
