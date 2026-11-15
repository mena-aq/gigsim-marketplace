"""Durable review, revalidation and exact-payload external execution."""

from langgraph.types import interrupt

from agent.execution import NodeContext, review_payload
from agent.handoffs import ApprovalRequest
from agent.state import GigBidState
from mcp_servers.common.errors import ToolFailure
from mcp_servers.common.schemas import MessageRequest, ProposalRequest


async def preview(state: GigBidState, ctx: NodeContext) -> dict:
    draft = state["draft"]
    key = (
        state["thread_id"]
        + ":"
        + state.get("turn_id", "initial")
        + ":"
        + str(len(state.get("edits", [])))
    )
    if state.get("conversation_id"):
        request = MessageRequest(
            conversation_id=state["conversation_id"],
            body=draft["cover_letter"],
            idempotency_key=key,
        )
        tool = "send_message"
    else:
        spec = state["analyses"]["job_spec"]
        expected = spec.get("screening_questions", [])
        if [
            answer["question"] for answer in draft.get("screening_answers", [])
        ] != expected:
            raise ToolFailure(
                "screening_mismatch",
                "Answer every screening question in the posted order",
            )
        request = ProposalRequest(
            job_id=state["job_id"],
            cover_letter=draft["cover_letter"],
            screening_answers=draft.get("screening_answers", []),
            idempotency_key=key,
            skills_mentioned=[
                skill
                for skill in state["job"].get("skills", [])
                if skill.lower() in draft["cover_letter"].lower()
            ],
        )
        tool = "submit_proposal"
    result = await ctx.tool(
        "approval_executor",
        tool,
        {
            "request": request.model_copy(update={"dry_run": True}).model_dump(
                mode="json"
            )
        },
    )
    price = dict(state.get("price", {}))
    if tool == "submit_proposal":
        balance = await ctx.tool("pricing", "get_connects_balance", {})
        if (
            balance["balance"] - result["connects_cost"]
            < ctx.config["orchestration"]["minimum_connects_reserve"]
        ):
            raise ToolFailure(
                "connects_reserve", "This proposal would exceed the Connects reserve"
            )
        request.expected_connects_cost = result["connects_cost"]
        price.update(
            connects_cost=result["connects_cost"], connects_balance=balance["balance"]
        )
    return {
        "request": request.model_dump(mode="json"),
        "preview": result,
        "price": price,
        "status": "awaiting_approval",
        "approval": {},
    }


async def approval(state: GigBidState) -> dict:
    payload = review_payload(state)
    decision = ApprovalRequest.model_validate(interrupt(payload)).model_dump(
        mode="json"
    )
    if decision["review_hash"] != payload["review_hash"]:
        return {
            "status": "needs_attention",
            "errors": {
                "approval": {"code": "stale_review", "message": "Review has changed"}
            },
        }
    if decision["action"] == "reject":
        return {"approval": decision, "status": "rejected"}
    if decision["action"] == "edit":
        draft = dict(state["draft"])
        if decision["cover_letter"] is not None:
            draft["cover_letter"] = decision["cover_letter"]
        if decision["screening_answers"] is not None:
            draft["screening_answers"] = decision["screening_answers"]
        edits = state.get("edits", []) + [{"before": state["draft"], "after": draft}]
        return {"draft": draft, "edits": edits, "approval": {}, "status": "running"}
    return {"approval": decision, "status": "approved"}


async def execute(state: GigBidState, ctx: NodeContext) -> dict:
    from agent.nodes.compliance import policy

    fields = {
        "cover_letter": state["draft"]["cover_letter"],
        **{
            str(index): answer["answer"]
            for index, answer in enumerate(state["draft"].get("screening_answers", []))
        },
    }
    for field, text in fields.items():
        report = state.get("verification", {}).get(field, {})
        if report.get("status") != "verified" or report.get("cleaned_draft") != text:
            raise ToolFailure(
                "verification_incomplete",
                "Every outgoing field must match its verified text before sending",
            )

    if state.get("policy_hash") != policy(ctx.config)[2]:
        raise ToolFailure(
            "policy_changed", "Policy changed after review; a new review is required"
        )
    if (
        state.get("approval", {}).get("action") != "approve"
        or state["approval"]["review_hash"] != review_payload(state)["review_hash"]
    ):
        raise ToolFailure(
            "approval_required", "Approve the exact checked request before sending"
        )
    tool = "send_message" if state.get("conversation_id") else "submit_proposal"
    if ctx.services.grant is None:
        raise ToolFailure(
            "approval_issuer_unavailable", "Trusted approval issuer is unavailable"
        )
    await ctx.services.grant(state, tool, state["request"])
    result = await ctx.tool("approval_executor", tool, {"request": state["request"]})
    return {"result": result, "status": "sent"}
