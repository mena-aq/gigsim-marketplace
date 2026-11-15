"""Shared terminal routing and explicitly promoted edit memory."""

from agent.execution import NodeContext
from agent.memory.store import promote_edits
from agent.state import GigBidState


def blocked(state):
    return bool(state.get("errors"))


async def stop(state):
    attention = any(
        any(
            word in error.get("code", "")
            for word in (
                "budget",
                "verification",
                "verified",
                "evidence",
                "risk_evidence",
                "screening",
                "model_response",
                "model_output",
                "connects",
                "approval",
                "preview_changed",
                "policy_changed",
                "floor",
            )
        )
        for error in state.get("errors", {}).values()
    )
    return {"status": "needs_attention" if attention else "dead_letter"}


async def learn(state: GigBidState, ctx: NodeContext) -> dict:
    if ctx.services.store is not None:
        await promote_edits(ctx.services.store, state)
    return {}
