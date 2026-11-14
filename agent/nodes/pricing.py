"""Produce a bounded price recommendation and current Connects balance."""

from statistics import median

from agent.execution import NodeContext
from agent.handoffs import PriceQuote
from agent.state import GigBidState
from mcp_servers.common.errors import ToolFailure


async def pricing(state: GigBidState, ctx: NodeContext) -> dict:
    balance = await ctx.tool("pricing", "get_connects_balance", {})
    sample = await ctx.tool(
        "pricing",
        "search_jobs",
        {"request": {"category": state["job"].get("category")}},
    )
    amounts = [
        job["budget_max"]
        for job in sample["items"]
        if job.get("budget_max") is not None
    ]
    statistics = {
        "sample_size": len(amounts),
        "median_posted_maximum": median(amounts) if amounts else None,
        "source": "current marketplace search page; posted budgets, not awarded contract prices",
    }
    quote = await ctx.ask(
        "pricing",
        {
            "job_spec": state["analyses"]["job_spec"],
            "client_history": state["analyses"].get("client_history"),
            "outcome_memory": state.get("outcomes", []),
            "balance": balance,
            "minimum_price": ctx.config["orchestration"]["minimum_price"],
            "market_statistics": statistics,
        },
        PriceQuote,
    )
    quote["connects_balance"] = balance["balance"]
    if quote["amount"] < ctx.config["orchestration"]["minimum_price"]:
        raise ToolFailure(
            "below_floor", "Suggested price is below the configured floor"
        )
    if state["job"].get("budget_max") and quote["amount"] > state["job"]["budget_max"]:
        raise ToolFailure("over_budget", "Suggested price exceeds the posted budget")
    return {"price": {**quote, "market_statistics": statistics}}
