"""Read client messages, classify intent and propose an approved response."""

from agent.execution import NodeContext
from agent.handoffs import ConversationIntent, ProposalDraft
from agent.state import GigBidState


async def read_messages(state: GigBidState, ctx: NodeContext) -> dict:
    messages = await ctx.tool(
        "liaison", "list_messages", {"conversation_id": state["conversation_id"]}
    )
    return {
        "messages": messages,
        "style": await ctx.memory("style"),
        "status": "running",
    }


async def classify_intent(state: GigBidState, ctx: NodeContext) -> dict:
    return {
        "intent": await ctx.ask(
            "intent", {"untrusted_messages": state["messages"]}, ConversationIntent
        )
    }


async def liaison(state: GigBidState, ctx: NodeContext) -> dict:
    slots = (
        await ctx.tool("liaison", "get_free_slots", {"days_ahead": 7})
        if state["intent"]["intent"] == "interview_request"
        else {}
    )
    draft = await ctx.ask(
        "liaison",
        {
            "untrusted_messages": state["messages"],
            "intent": state["intent"],
            "available_slots": slots,
            "style_memory": state.get("style", []),
        },
        ProposalDraft,
    )
    return {"draft": draft, "slots": slots, "evidence": []}
