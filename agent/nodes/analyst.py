"""Extract a structured job specification from untrusted marketplace data."""

from agent.execution import NodeContext
from agent.handoffs import JobSpec
from agent.state import GigBidState


async def analyst(state: GigBidState, ctx: NodeContext) -> dict:
    spec = await ctx.ask("analyst", {"untrusted_job": state["job"]}, JobSpec)
    spec["job_id"] = state["job"]["id"]
    for field in (
        "title",
        "budget_min",
        "budget_max",
        "timeline_days",
        "screening_questions",
    ):
        if field in state["job"]:
            spec[field] = state["job"][field]
    return {"analyses": {"job_spec": spec}}
