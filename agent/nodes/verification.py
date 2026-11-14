"""Verify every text field through Portfolio MCP before review or sending."""

from agent.execution import NodeContext
from agent.state import GigBidState
from mcp_servers.common.errors import ToolFailure


async def verify(state: GigBidState, ctx: NodeContext) -> dict:
    draft = dict(state["draft"])
    if not draft["cover_letter"].strip() or any(
        not answer["answer"].strip() for answer in draft.get("screening_answers", [])
    ):
        raise ToolFailure(
            "empty_verified_draft", "No safe text remains in a required draft field"
        )
    ids = [item["chunk_id"] for item in state.get("evidence", [])][:20]
    reports = {}
    failed = False
    for key, text in [("cover_letter", draft["cover_letter"])] + [
        (str(index), answer["answer"])
        for index, answer in enumerate(draft.get("screening_answers", []))
    ]:
        report = await ctx.tool(
            "verifier", "verify_claims", {"request": {"draft": text, "chunk_ids": ids}}
        )
        reports[key] = report
        if report["status"] != "verified":
            failed = True
        if key == "cover_letter":
            draft[key] = report["cleaned_draft"]
        else:
            answers = [dict(answer) for answer in draft["screening_answers"]]
            answers[int(key)]["answer"] = report["cleaned_draft"]
            draft["screening_answers"] = answers
    if failed:
        return {
            "draft": draft,
            "verification": reports,
            "verification_failed": True,
            **(
                {
                    "errors": {
                        "verify": {
                            "code": "verification_incomplete",
                            "message": "Reply verification needs attention; no message was sent",
                        }
                    }
                }
                if state.get("conversation_id")
                else {}
            ),
            "critique": {
                "verdict": "revise",
                "issues": [
                    "Verification was incomplete; write a shorter draft with at most one exact source-backed experience sentence and one simple future plan. Answer every screening question briefly. Do not repeat rejected claims."
                ],
            },
        }
    if not draft["cover_letter"].strip() or any(
        not answer["answer"].strip() for answer in draft.get("screening_answers", [])
    ):
        return {
            "draft": draft,
            "verification": reports,
            "errors": {
                "verify": {
                    "code": "empty_verified_draft",
                    "message": "No verified text remains in a required field; review the verification details",
                }
            },
        }
    return {"draft": draft, "verification": reports, "verification_failed": False}
