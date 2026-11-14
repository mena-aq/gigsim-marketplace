"""Durable conversation turns with the same exact-action review gate."""

from langgraph.graph import END, START, StateGraph

from agent.execution import GraphServices, guarded
from agent.graphs.common import blocked, learn, stop
from agent.nodes.approval import approval, execute, preview
from agent.nodes.client_liaison import classify_intent, liaison, read_messages
from agent.nodes.compliance import compliance
from agent.nodes.verification import verify
from agent.state import GigBidState


def build_conversation_graph(
    services: GraphServices | None = None, *, checkpointer=None, store=None
):
    services = services or GraphServices(store=store)
    graph = StateGraph(GigBidState)
    functions = {
        "read_messages": read_messages,
        "classify_intent": classify_intent,
        "liaison": liaison,
        "verify": verify,
        "compliance": compliance,
        "preview": preview,
        "execute": execute,
        "learn": learn,
    }
    for name, function in functions.items():
        graph.add_node(name, guarded(name, function, services))
    graph.add_node("approval", approval)
    graph.add_node("stop", stop)

    async def scam_block(state):
        return {
            "status": "blocked",
            "compliance": {"passed": False, "violations": [state["intent"]["reason"]]},
        }

    graph.add_node("scam_block", scam_block)

    async def compliance_block(state):
        return {"status": "blocked"}

    graph.add_node("compliance_block", compliance_block)
    graph.add_edge(START, "read_messages")
    for left, right in (
        ("read_messages", "classify_intent"),
        ("liaison", "verify"),
        ("verify", "compliance"),
        ("preview", "approval"),
        ("execute", "learn"),
    ):
        graph.add_conditional_edges(
            left,
            lambda state, target=right: "stop" if blocked(state) else target,
            ["stop", right],
        )
    graph.add_conditional_edges(
        "classify_intent",
        lambda state: (
            "stop"
            if blocked(state)
            else (
                "scam_block"
                if state["intent"]["intent"] == "scam_signal"
                else "liaison"
            )
        ),
        ["stop", "scam_block", "liaison"],
    )
    graph.add_conditional_edges(
        "compliance",
        lambda state: (
            "stop"
            if blocked(state)
            else ("preview" if state["compliance"]["passed"] else "compliance_block")
        ),
        ["stop", "preview", "compliance_block"],
    )
    graph.add_conditional_edges(
        "approval",
        lambda state: (
            "verify"
            if state["status"] == "running"
            else ("execute" if state["status"] == "approved" else END)
        ),
        ["verify", "execute", END],
    )
    for name in ("stop", "scam_block", "compliance_block", "learn"):
        graph.add_edge(name, END)
    return graph.compile(
        checkpointer=checkpointer, store=store, name="gigbid_conversation"
    )
