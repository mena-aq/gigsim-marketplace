"""Only this adapter calls GigSim REST; every attempt shares the Redis quota."""

import asyncio
import random

import httpx
from pydantic import ValidationError

from mcp_servers.common.schemas import (
    ClientHistory,
    ConnectsOut,
    ConversationOut,
    JobOut,
    JobPage,
    MessageOut,
)
from mcp_servers.common.security import TRACE_ID, ToolFailure

RATE_LIMIT = """
local now = redis.call('TIME')
local ms = now[1]*1000 + math.floor(now[2]/1000)
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ms-60000)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[1]) then
 local first = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
 return math.max(1, tonumber(first[2])+60000-ms)
end
local seq = redis.call('INCR', KEYS[1]..':seq')
redis.call('ZADD', KEYS[1], ms, ms..':'..seq)
redis.call('PEXPIRE', KEYS[1], 61000)
redis.call('PEXPIRE', KEYS[1]..':seq', 61000)
return 0
"""


class GigSimAdapter:
    def __init__(self, runtime):
        self.runtime = runtime

    async def request(self, who, method, path, *, params=None, payload=None):
        settings = self.runtime.settings
        async with httpx.AsyncClient(
            base_url=settings.gigsim_base_url,
            timeout=settings.mcp_timeout_seconds,
            transport=self.runtime.transport,
        ) as client:
            for attempt in range(3):
                wait = await self.runtime.redis.eval(
                    RATE_LIMIT,
                    1,
                    f"gigbid:upstream:{who.persona}",
                    settings.mcp_requests_per_minute,
                )
                if wait:
                    raise ToolFailure(
                        "rate_limited",
                        "Marketplace request budget reached",
                        True,
                        wait / 1000,
                    )
                try:
                    response = await client.request(
                        method,
                        path,
                        headers={
                            "Authorization": f"Bearer {settings.simulator_token(who.persona)}",
                            "X-Trace-ID": TRACE_ID.get() or "",
                        },
                        params=params,
                        json=payload,
                    )
                except httpx.TransportError:
                    if attempt == 2:
                        raise ToolFailure(
                            "marketplace_unavailable",
                            "Marketplace is unreachable",
                            True,
                        ) from None
                    await asyncio.sleep(0.25 * 2**attempt + random.random() * 0.1)
                    continue
                if response.status_code == 429 or response.status_code >= 500:
                    try:
                        delay = max(
                            0,
                            float(
                                response.headers.get("Retry-After", 0.25 * 2**attempt)
                            ),
                        )
                    except ValueError:
                        delay = 1.0
                    if attempt == 2 or delay > 30:
                        raise ToolFailure(
                            "rate_limited"
                            if response.status_code == 429
                            else "marketplace_unavailable",
                            "Marketplace asked us to retry later",
                            True,
                            delay,
                        )
                    await asyncio.sleep(delay)
                    continue
                if response.status_code >= 400:
                    code = {
                        402: "insufficient_connects",
                        403: "forbidden",
                        404: "not_found",
                        409: "conflict",
                        422: "invalid_input",
                    }.get(response.status_code, "marketplace_error")
                    raise ToolFailure(
                        code,
                        f"Marketplace rejected the operation ({response.status_code})",
                    )
                try:
                    return response.json()
                except ValueError:
                    raise ToolFailure(
                        "invalid_upstream_response",
                        "Marketplace returned invalid JSON",
                        True,
                    ) from None
        raise ToolFailure(
            "marketplace_unavailable", "Marketplace retries exhausted", True
        )

    async def read(self, who, path, schema, params=None):
        data = await self.request(who, "GET", path, params=params)
        try:
            if isinstance(schema, list):
                return [
                    schema[0].model_validate(item).model_dump(mode="json")
                    for item in data
                ]
            return schema.model_validate(data).model_dump(mode="json")
        except (ValidationError, TypeError):
            raise ToolFailure(
                "invalid_upstream_response",
                "Marketplace response did not match its contract",
                True,
            ) from None

    async def search_jobs(self, who, request):
        return await self.read(
            who, "/jobs", JobPage, request.model_dump(exclude_none=True)
        )

    async def get_job(self, who, job_id):
        return await self.read(who, "/jobs/" + job_id, JobOut)

    async def get_client_history(self, who, client_id):
        return await self.read(who, "/clients/" + client_id + "/history", ClientHistory)

    async def get_connects_balance(self, who):
        return await self.read(who, "/connects", ConnectsOut)

    async def list_conversations(self, who):
        return await self.read(who, "/messages/conversations", [ConversationOut])

    async def list_messages(self, who, conversation_id):
        return await self.read(
            who, "/messages", [MessageOut], {"conversation_id": conversation_id}
        )
