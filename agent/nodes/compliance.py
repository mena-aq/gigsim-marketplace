"""Block drafts violating the file-backed platform policy."""

from agent.config import ROOT
from agent.execution import NodeContext
from agent.handoffs import ComplianceAssessment, ComplianceVerdict
from agent.state import GigBidState
from mcp_servers.common.errors import ToolFailure
from mcp_servers.common.security import fingerprint


def policy(config):
    import yaml

    settings = config["orchestration"]
    rules = (ROOT / settings["policy_file"]).read_text()
    checks = yaml.safe_load((ROOT / settings["enforcement_file"]).read_text())
    return rules, checks, fingerprint({"rules": rules, "checks": checks})


async def compliance(state: GigBidState, ctx: NodeContext) -> dict:
    import re

    rules, checks, digest = policy(ctx.config)
    text = (
        state["draft"]["cover_letter"]
        + "\n"
        + "\n".join(
            answer["answer"] for answer in state["draft"].get("screening_answers", [])
        )
    )
    violations = [
        rule["reason"] for rule in checks["rules"] if re.search(rule["pattern"], text)
    ]
    if violations:
        return {
            "compliance": {"passed": False, "violations": violations},
            "policy_hash": digest,
        }
    assessment = await ctx.ask(
        "compliance",
        {
            "policy": rules,
            "draft": {
                "cover_letter": state["draft"]["cover_letter"],
                "screening_answers": state["draft"].get("screening_answers", []),
            },
            "verification": {
                key: {
                    "status": report["status"],
                    "cleaned_draft": report["cleaned_draft"],
                }
                for key, report in state.get("verification", {}).items()
            },
        },
        ComplianceAssessment,
    )
    for finding in assessment["findings"]:
        if finding["quote"] not in text:
            raise ToolFailure(
                "invalid_policy_evidence",
                "Policy assessment quoted text absent from the outgoing draft",
            )
    verdict = ComplianceVerdict(
        passed=not assessment["findings"],
        violations=[
            f"{finding['category']}: {finding['reason']} ({finding['quote']})"
            for finding in assessment["findings"]
        ],
    ).model_dump()
    verdict["findings"] = assessment["findings"]
    if not state["draft"]["cover_letter"].strip():
        verdict = {"passed": False, "violations": ["No verified text remains"]}
    return {"compliance": verdict, "policy_hash": digest}
