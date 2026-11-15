"""R&D question C, arm (a): one agent, every read-only tool, no specialist nodes.

A small hand-written ReAct loop: the model picks a tool or finishes, sees the result,
and repeats up to `max_steps` times, then answers once with a decision and a letter.
It goes through NodeContext, so it shares the graph's model client, token budget,
tool gateway and audit hook. It has no write tools and never submits anything.
"""

from agent.execution import GraphServices, NodeContext
from agent.handoffs import AgentStep, SingleAgentResult
from mcp_servers.common.errors import ToolFailure

ROLE = "single_agent"
TOOLS = {
    "get_client_history": "Read the client's public history and reviews.",
    "search_evidence": "Search the freelancer's portfolio; put a query in 'query'.",
    "finish": "Stop gathering information and decide.",
}


def compact_history(history: dict) -> dict:
    return {
        "client": history.get("client"),
        "reviews": (history.get("reviews") or [])[:5],
        "proposals_received": history.get("proposals_received"),
    }


async def run_single_agent(
    services: GraphServices,
    job_id: str,
    *,
    user_id: str = "eval",
    trace_id: str = "single-agent",
    max_steps: int = 3,
) -> dict:
    ctx = NodeContext(services, {"user_id": user_id, "trace_id": trace_id, "tokens": 0})
    job = await ctx.tool(ROLE, "get_job", {"job_id": job_id})
    settings = ctx.config["orchestration"]
    observations: list[dict] = []
    evidence: list[dict] = []
    trace: list[dict] = []
    for _ in range(max_steps):
        step = await ctx.ask(
            ROLE,
            {
                "mode": "next_step",
                "untrusted_job": job,
                "tools": TOOLS,
                "observations": observations,
            },
            AgentStep,
        )
        trace.append({"action": step["action"], "query": step["query"]})
        if step["action"] == "finish":
            break
        if any(
            o["tool"] == step["action"] and o["query"] == step["query"]
            for o in observations
        ):
            break  # repeating a call adds nothing; fall through to the answer
        if step["action"] == "get_client_history":
            result = compact_history(
                await ctx.tool(
                    ROLE, "get_client_history", {"client_id": job["client_id"]}
                )
            )
        else:
            query = step["query"] or job["title"] + "\n" + job["description"]
            found = await ctx.tool(
                ROLE, "search_evidence", {"request": {"requirement": query, "k": 5}}
            )
            known = {item["chunk_id"] for item in evidence}
            evidence += [i for i in found["items"] if i["chunk_id"] not in known]
            result = [
                {"id": f"E{n + 1}", "text": item["text"]}
                for n, item in enumerate(evidence)
            ]
        observations.append(
            {"tool": step["action"], "query": step["query"], "result": result}
        )
    answer = await ctx.ask(
        ROLE,
        {
            "mode": "final",
            "untrusted_job": job,
            "observations": observations,
            "evidence": [
                {"id": f"E{n + 1}", "text": item["text"]}
                for n, item in enumerate(evidence)
            ],
            "minimum_price": settings["minimum_price"],
            "maximum_cover_letter_words": settings["writer_words"],
        },
        SingleAgentResult,
    )
    if answer["action"] == "bid" and not answer["cover_letter"].strip():
        raise ToolFailure("empty_draft", "Agent chose to bid but wrote no letter")
    return {
        **answer,
        "job": job,
        "evidence": evidence,
        "trace": trace,
        "tokens": ctx.tokens,
    }
