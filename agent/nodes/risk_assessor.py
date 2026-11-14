"""Assess untrusted job content and public client history."""

from agent.execution import NodeContext
from agent.handoffs import RiskAssessment, RiskReport
from agent.nodes.compliance import policy
from agent.state import GigBidState
from mcp_servers.common.errors import ToolFailure


async def risk(state: GigBidState, ctx: NodeContext) -> dict:
    client_id = state["job"].get("client_id")
    history = (
        await ctx.tool("risk", "get_client_history", {"client_id": client_id})
        if client_id
        else None
    )
    assessment = await ctx.ask(
        "risk",
        {
            "untrusted_job": state["job"],
            "untrusted_history": {
                "client": history["client"],
                "reviews": history["reviews"][:5],
                "proposals_received": history["proposals_received"],
            }
            if history
            else None,
        },
        RiskAssessment,
    )
    import json

    settings = ctx.config["orchestration"]
    score = settings["risk_levels"]["none"]
    flags = []
    for finding in assessment["findings"]:
        source = (
            state["job"]["title"] + "\n" + state["job"]["description"]
            if finding["source"] == "job"
            else json.dumps(history, ensure_ascii=False)
        )
        if finding["quote"] not in source:
            raise ToolFailure(
                "invalid_risk_evidence",
                "Risk assessment quoted text absent from the job or client history",
            )
        flags.append(finding["reason"])
        score = max(score, settings["risk_levels"][finding["level"]])
    if history is None:
        score = max(score, settings["missing_client_risk"])
        flags.append("Client history is unavailable")
    else:
        client = history["client"]
        if not client["payment_verified"]:
            score = max(score, settings["unverified_payment_risk"])
            flags.append("Client payment is not verified")
        if client["hire_rate"] <= settings["low_hire_rate"]:
            score = max(score, settings["low_hire_rate_risk"])
            flags.append("Client hire rate is below the configured floor")
    report = RiskReport(
        score=score,
        flags=flags,
        explanation="; ".join(flags)
        if flags
        else "No source-backed marketplace risk indicators found",
    ).model_dump()
    report["findings"] = assessment["findings"]
    import re

    _, checks, _ = policy(ctx.config)
    for rule in checks.get("risk_rules", []):
        if re.search(rule["pattern"], state["job"]["description"]):
            report["score"] = max(report["score"], rule["minimum_risk"])
            report["flags"].append(rule["reason"])
            report["explanation"] += "; " + rule["reason"]
    return {"analyses": {"risk": report, "client_history": history}}
