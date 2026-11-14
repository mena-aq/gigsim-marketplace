"""Review quality after fail-closed claim verification."""

from agent.execution import NodeContext
from agent.handoffs import Critique
from agent.state import GigBidState


async def critic(state: GigBidState, ctx: NodeContext) -> dict:
    critique = await ctx.ask(
        "critic",
        {
            "untrusted_job": state["job"],
            "draft": state["draft"],
            "verification": state["verification"],
            "max_words": ctx.config["orchestration"]["max_proposal_words"],
        },
        Critique,
    )
    if (
        len(state["draft"]["cover_letter"].split())
        > ctx.config["orchestration"]["max_proposal_words"]
    ):
        critique = {
            "verdict": "revise",
            "issues": ["Proposal exceeds configured word limit"],
        }
    return {"critique": critique}
