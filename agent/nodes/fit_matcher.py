"""Match requirements against actual retrieved chunks."""

from agent.execution import NodeContext
from agent.handoffs import FitReport, RequirementMatch
from agent.state import GigBidState
from mcp_servers.common.errors import ToolFailure


async def matcher(state: GigBidState, ctx: NodeContext) -> dict:
    job = state["job"]
    found = await ctx.tool(
        "matcher",
        "search_evidence",
        {"request": {"requirement": job["title"] + "\n" + job["description"], "k": 5}},
    )
    evidence = found["items"]
    if not evidence:
        return {
            "analyses": {
                "fit": FitReport(
                    score=0, missing_skills=job.get("skills", [])
                ).model_dump()
            },
            "evidence": [],
        }
    from typing import Literal

    from pydantic import Field, create_model

    aliases = {f"E{index + 1}": item["chunk_id"] for index, item in enumerate(evidence)}
    citation = Literal[tuple(aliases)]
    match_schema = create_model(
        "SourceMatch",
        __base__=RequirementMatch,
        evidence_ids=(list[citation], Field(max_length=len(aliases))),
    )
    schema = create_model(
        "SourceFit",
        __base__=FitReport,
        evidence_ids=(list[citation], Field(max_length=len(aliases))),
        requirement_matches=(list[match_schema], Field(min_length=1, max_length=6)),
    )
    fit = await ctx.ask(
        "matcher",
        {
            "untrusted_job": job,
            "evidence": [
                {"id": alias, "text": item["text"], "type": item.get("type")}
                for alias, item in zip(aliases, evidence, strict=True)
            ],
        },
        schema,
    )
    fit["evidence_ids"] = [aliases[key] for key in fit["evidence_ids"]]
    for match in fit["requirement_matches"]:
        match["evidence_ids"] = [aliases[key] for key in match["evidence_ids"]]
    owned = {item["chunk_id"] for item in evidence}
    ids = set(fit["evidence_ids"]) | {
        item for match in fit["requirement_matches"] for item in match["evidence_ids"]
    }
    if not ids.issubset(owned):
        raise ToolFailure(
            "invalid_evidence", "Fit report references unretrieved evidence"
        )
    if not evidence:
        fit["score"] = 0
    return {"analyses": {"fit": fit}, "evidence": evidence}
