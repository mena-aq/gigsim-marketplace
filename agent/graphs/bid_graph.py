"""Hand-written, parallel bidding graph with durable human review."""

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from agent.execution import GraphServices, NodeContext, guarded
from agent.graphs.common import blocked, learn, stop
from agent.handoffs import BidDecision
from agent.nodes.analyst import analyst
from agent.nodes.approval import approval, execute, preview
from agent.nodes.compliance import compliance
from agent.nodes.critic import critic
from agent.nodes.fit_matcher import matcher
from agent.nodes.pricing import pricing
from agent.nodes.risk_assessor import risk
from agent.nodes.scout import scout
from agent.nodes.verification import verify
from agent.nodes.writer import writer
from agent.state import GigBidState


async def decision(state: GigBidState, ctx: NodeContext) -> dict:
    reports = state["analyses"]
    thresholds = ctx.config["thresholds"]
    if reports["risk"]["score"] >= thresholds["maximum_risk_score"]:
        choice = BidDecision(
            action="skip",
            reason=f"Risk {reports['risk']['score']:.2f} meets the {thresholds['maximum_risk_score']:.2f} cutoff: {reports['risk']['explanation']}",
        )
    elif reports["fit"]["score"] < thresholds["minimum_fit_score"]:
        choice = BidDecision(
            action="watch",
            reason=f"Fit {reports['fit']['score']:.2f} is below the {thresholds['minimum_fit_score']:.2f} minimum",
        )
    else:
        choice = BidDecision(
            action="bid", reason="Fit and risk meet configured thresholds"
        )
    return {
        "decision": choice.model_dump(),
        "status": choice.action if choice.action != "bid" else "running",
    }


def build_bid_graph(
    services: GraphServices | None = None,
    *,
    checkpointer=None,
    store=None,
    interrupt_before=None,
):
    services = services or GraphServices(store=store)
    graph = StateGraph(GigBidState)
    functions = {
        "scout": scout,
        "analyst": analyst,
        "risk": risk,
        "matcher": matcher,
        "decision": decision,
        "pricing": pricing,
        "writer": writer,
        "verify": verify,
        "critic": critic,
        "compliance": compliance,
        "preview": preview,
        "execute": execute,
        "learn": learn,
    }
    for name, function in functions.items():
        graph.add_node(name, guarded(name, function, services))
    graph.add_node("approval", approval)
    graph.add_node("stop", stop)
    graph.add_edge(START, "scout")
    graph.add_conditional_edges(
        "scout",
        lambda state: (
            "stop"
            if blocked(state)
            else [Send(name, state) for name in ("analyst", "risk", "matcher")]
        ),
        ["stop", "analyst", "risk", "matcher"],
    )

    async def join(state):
        return {}

    graph.add_node("join", join)
    graph.add_edge(["analyst", "risk", "matcher"], "join")
    graph.add_conditional_edges(
        "join",
        lambda state: "stop" if blocked(state) else "decision",
        ["stop", "decision"],
    )
    graph.add_conditional_edges(
        "decision",
        lambda state: (
            "stop"
            if blocked(state)
            else ("pricing" if state["decision"]["action"] == "bid" else END)
        ),
        ["stop", "pricing", END],
    )
    for left, right in (
        ("pricing", "writer"),
        ("writer", "verify"),
        ("execute", "learn"),
    ):
        graph.add_conditional_edges(
            left,
            lambda state, target=right: "stop" if blocked(state) else target,
            ["stop", right],
        )

    def after_verify(state):
        if blocked(state):
            return "stop"
        if state.get("verification_failed"):
            if (
                state.get("edits")
                or state.get("revisions", 0)
                >= services.config["budgets"]["max_revisions"]
            ):
                return "verification_attention"
            return "writer"
        return "compliance" if state.get("edits") else "critic"

    async def verification_attention(state):
        return {
            "status": "needs_attention",
            "errors": {
                "verify": {
                    "code": "verification_incomplete",
                    "message": "Verification could not complete safely. See sentence-level diagnostics and replay from Writer to redraft.",
                }
            },
        }

    graph.add_node("verification_attention", verification_attention)
    graph.add_edge("verification_attention", END)
    graph.add_conditional_edges(
        "verify",
        after_verify,
        ["stop", "compliance", "critic", "writer", "verification_attention"],
    )

    def after_critic(state):
        if blocked(state):
            return "stop"
        if state["critique"]["verdict"] == "revise":
            return (
                "writer"
                if state.get("revisions", 0)
                < services.config["budgets"]["max_revisions"]
                else "exhausted"
            )
        return "compliance"

    async def exhausted(state):
        return {
            "status": "needs_attention",
            "errors": {
                "critic": {
                    "code": "revision_limit",
                    "message": "Draft did not pass critique within the revision limit",
                }
            },
        }

    async def compliance_block(state):
        return {"status": "blocked"}

    graph.add_node("exhausted", exhausted)
    graph.add_node("compliance_block", compliance_block)
    graph.add_conditional_edges(
        "critic", after_critic, ["stop", "writer", "exhausted", "compliance"]
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
        "preview",
        lambda state: "stop" if blocked(state) else "approval",
        ["stop", "approval"],
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
    for name in ("stop", "exhausted", "compliance_block", "learn"):
        graph.add_edge(name, END)
    return graph.compile(
        checkpointer=checkpointer,
        store=store,
        name="gigbid_bid",
        interrupt_before=interrupt_before,
    )
