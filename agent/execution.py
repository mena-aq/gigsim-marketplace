"""Dependency injection, node budgets, retries and audit outside working state."""

import asyncio
import time
from dataclasses import dataclass

from agent.config import load_graph_config
from agent.mcp_client import SERVER_TOOLS, MCPGateway
from agent.model import NodeModel
from mcp_servers.common.errors import ToolFailure
from mcp_servers.common.security import fingerprint


@dataclass
class GraphServices:
    token: str = ""
    config: dict | None = None
    store: object = None
    model: object = None
    audit: object = None
    grant: object = None
    gateway_factory: object = MCPGateway

    def __post_init__(self):
        self.config = self.config or load_graph_config()
        self.model = self.model or NodeModel(self.config)


class NodeContext:
    def __init__(self, services, state):
        self.services = services
        self.state = state
        self.config = services.config
        self.tokens = 0

    async def ask(self, role, payload, schema):
        # Reserve a context + output window before starting another model call.
        settings = self.config["orchestration"]
        reserve = settings["context_tokens"] + settings.get(
            "output_tokens_by_role", {}
        ).get(role, settings["output_tokens"])
        if (
            self.state.get("tokens", 0) + self.tokens + reserve
            > self.config["budgets"]["max_tokens_per_job"]
        ):
            raise ToolFailure(
                "token_budget", "Thread token budget cannot cover another model call"
            )
        value, used = await self.services.model.ask(role, payload, schema)
        self.tokens += used
        return value.model_dump(mode="json")

    async def tool(self, role, tool, arguments):
        audit_arguments = arguments
        gateway = self.services.gateway_factory(
            self.services.token, role, self.state["trace_id"]
        )
        if tool in SERVER_TOOLS["marketplace"]:
            from agent.marketplace_port import MCPMarketplacePort
            from mcp_servers.common.schemas import (
                MessageRequest,
                ProposalRequest,
                SearchJobs,
            )

            port = MCPMarketplacePort(gateway)
            arguments = dict(arguments)
            if "request" in arguments:
                schema = (
                    SearchJobs
                    if tool == "search_jobs"
                    else (MessageRequest if tool == "send_message" else ProposalRequest)
                )
                arguments["request"] = schema.model_validate(arguments["request"])
            value = await getattr(port, tool)(**arguments)
            result = (
                [item.model_dump(mode="json") for item in value]
                if isinstance(value, list)
                else value.model_dump(mode="json")
            )
        else:
            result = await gateway.call(tool, arguments)
        if self.services.audit:
            await self.services.audit(
                self.state,
                "tool." + tool,
                {"arguments": audit_arguments, "result": result},
            )
        self.tokens += (
            usage_tokens(result.get("diagnostics", {}))
            if isinstance(result, dict)
            else 0
        )
        return result

    async def memory(self, kind):
        if self.services.store is None:
            return []
        items = await self.services.store.asearch(
            (self.state["user_id"], kind), limit=100
        )
        return [item.value for item in items]


def usage_tokens(value):
    if isinstance(value, list):
        return sum(usage_tokens(item) for item in value)
    if isinstance(value, dict):
        return sum(
            item
            for key, item in value.items()
            if key in {"prompt_tokens", "completion_tokens"} and isinstance(item, int)
        ) + sum(
            usage_tokens(item)
            for item in value.values()
            if isinstance(item, (dict, list))
        )
    return 0


def guarded(name, function, services):
    async def node(state):
        ctx = NodeContext(services, state)
        budget = services.config["budgets"]
        settings = services.config["orchestration"]
        start = time.perf_counter()
        update = {}
        try:
            if (
                state.get("steps", 0) >= budget["max_graph_steps"]
                or state.get("tokens", 0) >= budget["max_tokens_per_job"]
            ):
                raise ToolFailure(
                    "thread_budget", "Thread step or token budget exhausted"
                )
            for attempt in range(settings["node_attempts"]):
                try:
                    async with asyncio.timeout(settings["node_timeout_seconds"]):
                        update = await function(state, ctx)
                    break
                except (TimeoutError, ToolFailure) as exc:
                    failure = (
                        exc
                        if isinstance(exc, ToolFailure)
                        else ToolFailure("node_timeout", "Node timed out", True)
                    )
                    if (
                        not failure.retryable
                        or attempt + 1 == settings["node_attempts"]
                    ):
                        raise failure
                    # Long Retry-After values are handled by the durable worker queue.
                    if failure.retry_after and failure.retry_after > 2:
                        raise failure
                    await asyncio.sleep(failure.retry_after or (0.25 * 2**attempt))
        except ToolFailure as exc:
            if exc.retryable:
                if services.audit:
                    await services.audit(
                        state, "node." + name, {"error": exc.code, "tokens": ctx.tokens}
                    )
                raise
            update = {"errors": {name: {"code": exc.code, "message": exc.message}}}
        if state.get("tokens", 0) + ctx.tokens > budget["max_tokens_per_job"]:
            update["errors"] = {
                name: {
                    "code": "token_budget",
                    "message": "Thread token budget exhausted",
                }
            }
        if services.audit:
            await services.audit(
                state,
                "node." + name,
                {
                    "update": update,
                    "tokens": ctx.tokens,
                    "seconds": time.perf_counter() - start,
                },
            )
        return {**update, "steps": 1, "tokens": ctx.tokens}

    return node


def review_payload(state):
    payload = {
        "draft": state["draft"],
        "evidence": state.get("evidence", []),
        "verification": state.get("verification", {}),
        "risk": state.get("analyses", {}).get("risk", {}),
        "price": state.get("price", {}),
        "preview": state["preview"],
        "request": state["request"],
        "critique": state.get("critique", {}),
        "compliance": state["compliance"],
        "policy_hash": state.get("policy_hash"),
    }
    return {**payload, "review_hash": fingerprint(payload)}
