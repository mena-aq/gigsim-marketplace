"""Load the job handed off by a tenant-scoped scouting request."""

from agent.execution import NodeContext
from agent.state import GigBidState


async def scout(state: GigBidState, ctx: NodeContext) -> dict:
    job = await ctx.tool("scout", "get_job", {"job_id": state["job_id"]})
    return {
        "job": job,
        "status": "running",
        "style": await ctx.memory("style"),
        "outcomes": await ctx.memory("outcome"),
    }
