"""Real LangGraph execution with deterministic model and MCP boundaries."""

from copy import deepcopy

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command, Overwrite

from agent.execution import GraphServices, review_payload
from agent.graphs.bid_graph import build_bid_graph
from agent.graphs.conversation_graph import build_conversation_graph
from agent.memory.store import promote_edits, promote_outcome
from mcp_servers.common.errors import ToolFailure


class Model:
    def __init__(self):
        self.calls = []
        self.revise = 0
        self.risk = 0.1
        self.compliance = True

    async def ask(self, role, payload, schema):
        self.calls.append(role)
        values = {
            "analyst": {
                "job_id": "job",
                "title": "Python forecasting",
                "required_skills": ["Python"],
            },
            "risk": {
                "findings": [
                    {
                        "level": "high",
                        "source": "job",
                        "quote": payload.get("untrusted_job", {}).get(
                            "description", ""
                        ),
                        "reason": "Client history",
                    }
                ]
                if self.risk >= 0.9
                else []
            },
            "matcher": {
                "score": 0.9,
                "evidence_ids": ["E1"],
                "requirement_matches": [
                    {
                        "requirement": "Python",
                        "evidence_ids": ["E1"],
                        "reason": "Source",
                    }
                ],
            },
            "pricing": {
                "amount": 500,
                "rationale": "Scope estimate",
                "connects_balance": 60,
            },
            "writer": {
                "job_id": "job",
                "cover_letter": "I built Python forecasting. How is your data structured?",
                "screening_answers": [
                    {"question": question, "answer": "Could you share more detail?"}
                    for question in payload.get("untrusted_job", {}).get(
                        "screening_questions", []
                    )
                ],
            },
            "critic": {
                "verdict": "revise"
                if self.calls.count("critic") <= self.revise
                else "pass",
                "issues": [],
            },
            "compliance": {
                "findings": []
                if self.compliance
                else [
                    {
                        "category": "guaranteed_outcome",
                        "quote": payload.get("draft", {}).get("cover_letter", ""),
                        "reason": "Policy violation",
                    }
                ],
            },
            "intent": {
                "intent": "interview_request",
                "reason": "Client requests a meeting",
            },
            "liaison": {
                "job_id": "",
                "cover_letter": "Would tomorrow at 10 AM PKT work?",
            },
        }
        return schema.model_validate(values[role]), 100


class Tools:
    def __init__(self):
        self.calls = []
        self.receipts = {}
        self.fail_after_send = False

    def gateway(self, token, role, trace):
        outer = self

        class Gateway:
            async def call(self, name, args):
                outer.calls.append((name, deepcopy(args)))
                if name == "get_job":
                    return {
                        "id": "job",
                        "title": "Python forecasting",
                        "description": "Build a forecast",
                        "skills": ["Python"],
                        "budget_max": 1000,
                        "client_id": "client",
                        "status": "open",
                    }
                if name == "search_jobs":
                    return {"items": [], "total": 0, "page": 1, "page_size": 20}
                if name == "get_client_history":
                    return {
                        "client": {
                            "id": "client",
                            "name": "Client",
                            "total_spend": 5000,
                            "hire_rate": 0.9,
                            "avg_rating": 5,
                            "payment_verified": True,
                        },
                        "proposals_received": 0,
                        "past_proposals": [],
                        "reviews": [],
                    }
                if name == "get_connects_balance":
                    return {"freelancer_id": "ml_engineer", "balance": 60}
                if name == "search_evidence":
                    return {
                        "items": [
                            {"chunk_id": "chunk", "text": "Built Python forecasting."}
                        ],
                        "backend": "v0",
                    }
                if name == "verify_claims":
                    return {
                        "status": "verified",
                        "cleaned_draft": args["request"]["draft"],
                        "sentences": [],
                    }
                if name == "list_messages":
                    return [
                        {
                            "id": 1,
                            "conversation_id": "thread",
                            "sender": "client",
                            "body": "When can we meet?",
                            "sent_at": "2026-11-14T00:00:00Z",
                        }
                    ]
                if name == "get_free_slots":
                    return {"timezone": "Asia/Karachi", "slots": []}
                if name in {"submit_proposal", "send_message"}:
                    request = args["request"]
                    if request.get("dry_run"):
                        return {
                            "status": "dry_run",
                            "payload": request,
                            "connects_cost": 8 if name == "submit_proposal" else 0,
                        }
                    outer.receipts.setdefault(
                        request["idempotency_key"],
                        {
                            "status": "sent",
                            "payload": request,
                            "external_id": "receipt",
                        },
                    )
                    if outer.fail_after_send:
                        outer.fail_after_send = False
                        raise ToolFailure(
                            "marketplace_unavailable",
                            "Lost reply after write",
                            True,
                            60,
                        )
                    return outer.receipts[request["idempotency_key"]]
                raise AssertionError(name)

        return Gateway()


def initial(**extra):
    return {
        "user_id": "alice",
        "thread_id": "run",
        "trace_id": "trace",
        "job_id": "job",
        **extra,
    }


@pytest.fixture
def setup():
    model, tools = Model(), Tools()
    store = InMemoryStore()
    grants = []

    async def grant(state, tool, request):
        grants.append(deepcopy(request))

    services = GraphServices(
        model=model, gateway_factory=tools.gateway, store=store, grant=grant
    )
    saver = InMemorySaver()
    return services, saver, model, tools, grants


async def test_parallel_join_interrupt_resume_and_idempotent_recovery(setup):
    services, saver, model, tools, grants = setup
    graph = build_bid_graph(services, checkpointer=saver)
    config = {"configurable": {"thread_id": "alice:run"}}
    result = await graph.ainvoke(initial(), config)
    assert result["status"] == "awaiting_approval"
    snapshot = await graph.aget_state(config)
    assert set(snapshot.values["analyses"]) >= {"job_spec", "risk", "fit"}
    assert (
        len(
            [
                snap
                async for snap in graph.aget_state_history(config)
                if "decision" in snap.next
            ]
        )
        == 1
    )
    assert not tools.receipts and not grants
    # Recreate graph to simulate a restarted service using the same checkpointer.
    restarted = build_bid_graph(services, checkpointer=saver)
    approval = {
        "action": "approve",
        "review_hash": review_payload(snapshot.values)["review_hash"],
    }
    tools.fail_after_send = True
    with pytest.raises(ToolFailure):
        await restarted.ainvoke(Command(resume=approval), config)
    result = await restarted.ainvoke(None, config)
    assert result["status"] == "sent"
    assert len(tools.receipts) == 1
    assert grants[0] == grants[1]
    assert model.calls.count("writer") == 1


async def test_edit_is_reverified_and_requires_second_approval(setup):
    services, saver, model, tools, grants = setup
    graph = build_bid_graph(services, checkpointer=saver)
    config = {"configurable": {"thread_id": "edits"}}
    result = await graph.ainvoke(initial(), config)
    old_hash = review_payload(result)["review_hash"]
    result = await graph.ainvoke(
        Command(
            resume={
                "action": "edit",
                "review_hash": old_hash,
                "cover_letter": "How is your data structured?",
            }
        ),
        config,
    )
    assert result["status"] == "awaiting_approval"
    assert not tools.receipts and not grants
    assert model.calls.count("compliance") == 2
    assert len([name for name, args in tools.calls if name == "verify_claims"]) == 2
    assert review_payload(result)["review_hash"] != old_hash
    result = await graph.ainvoke(
        Command(
            resume={
                "action": "reject",
                "review_hash": review_payload(result)["review_hash"],
                "reason": "Prefer another job",
            }
        ),
        config,
    )
    assert result["status"] == "rejected" and not tools.receipts


@pytest.mark.parametrize(
    "revisions,expected", [(2, "awaiting_approval"), (3, "needs_attention")]
)
async def test_critic_revises_at_most_twice(setup, revisions, expected):
    services, saver, model, tools, _ = setup
    model.revise = revisions
    graph = build_bid_graph(services, checkpointer=saver)
    result = await graph.ainvoke(initial(), {"configurable": {"thread_id": "critic"}})
    assert model.calls.count("writer") == 3
    assert result["status"] == expected
    assert not tools.receipts


async def test_scam_skip_and_compliance_block(setup):
    services, saver, model, tools, _ = setup
    model.risk = 0.95
    graph = build_bid_graph(services, checkpointer=saver)
    result = await graph.ainvoke(initial(), {"configurable": {"thread_id": "scam"}})
    assert result["status"] == "skip" and "writer" not in model.calls
    model.risk = 0.1
    model.compliance = False
    result = await graph.ainvoke(initial(), {"configurable": {"thread_id": "blocked"}})
    assert result["status"] == "blocked" and not tools.receipts


async def test_budget_and_stale_review_fail_closed(setup):
    services, saver, model, tools, grants = setup
    graph = build_bid_graph(services, checkpointer=saver)
    result = await graph.ainvoke(
        initial(steps=100), {"configurable": {"thread_id": "budget"}}
    )
    assert result["status"] == "needs_attention" and not model.calls
    config = {"configurable": {"thread_id": "stale"}}
    await graph.ainvoke(initial(), config)
    result = await graph.ainvoke(
        Command(resume={"action": "approve", "review_hash": "0" * 64}), config
    )
    assert result["status"] == "needs_attention" and not grants and not tools.receipts


async def test_conversation_has_the_same_human_gate(setup):
    services, saver, _model, tools, grants = setup
    graph = build_conversation_graph(services, checkpointer=saver)
    config = {"configurable": {"thread_id": "conversation"}}
    result = await graph.ainvoke(initial(conversation_id="thread"), config)
    assert result["status"] == "awaiting_approval"
    assert result["intent"]["intent"] == "interview_request"
    assert not tools.receipts
    result = await graph.ainvoke(
        Command(
            resume={
                "action": "approve",
                "review_hash": review_payload(result)["review_hash"],
            }
        ),
        config,
    )
    assert result["status"] == "sent" and len(grants) == 1


async def test_memory_requires_distinct_approved_edits_and_confirmed_outcomes():
    store = InMemoryStore()
    state = initial(
        status="sent",
        edits=[
            {
                "before": {"cover_letter": "I am passionate. Can we discuss?"},
                "after": {"cover_letter": "Can we discuss?"},
            }
        ],
    )
    await promote_edits(store, state)
    await promote_edits(store, state)
    assert not await store.asearch(("alice", "style"))
    for index in range(2):
        await promote_edits(store, {**state, "thread_id": str(index)})
    assert len(await store.asearch(("alice", "style"))) == 1
    assert not await store.asearch(("bob", "style"))
    assert not await promote_outcome(store, "alice", "run", "ml", "hired", {})
    assert await promote_outcome(
        store, "alice", "run", "ml", "hired", {"confirmed": True}
    )
    assert not await promote_outcome(
        store, "alice", "pending", "ml", "submitted", {"confirmed": True}
    )


async def test_conversation_continues_in_same_thread_with_new_write_key(setup):
    services, saver, _model, tools, _grants = setup
    graph = build_conversation_graph(services, checkpointer=saver)
    config = {"configurable": {"thread_id": "conversation"}}
    state = await graph.ainvoke(initial(conversation_id="thread"), config)
    state = await graph.ainvoke(
        Command(
            resume={
                "action": "approve",
                "review_hash": review_payload(state)["review_hash"],
            }
        ),
        config,
    )
    key = state["request"]["idempotency_key"]
    state = await graph.ainvoke(
        {
            **state,
            "steps": 0,
            "tokens": 0,
            "errors": Overwrite({}),
            "analyses": Overwrite({}),
            "turn_id": "turn-two",
            "edits": [],
            "approval": {},
            "request": {},
            "preview": {},
            "result": {},
        },
        config,
    )
    assert state["status"] == "awaiting_approval"
    assert state["request"]["idempotency_key"] != key
    assert len(tools.receipts) == 1


async def test_configured_policy_blocks_contact_details_even_if_model_passes(setup):
    services, saver, _model, tools, _grants = setup
    graph = build_bid_graph(services, checkpointer=saver)
    config = {"configurable": {"thread_id": "unsafe-edit"}}
    state = await graph.ainvoke(initial(), config)
    state = await graph.ainvoke(
        Command(
            resume={
                "action": "edit",
                "review_hash": review_payload(state)["review_hash"],
                "cover_letter": "Contact me at private@example.com.",
            }
        ),
        config,
    )
    assert state["status"] == "blocked"
    assert "Email contact details are prohibited" in state["compliance"]["violations"]
    assert not tools.receipts


async def test_missing_verified_text_and_token_budget_stop_before_send(setup):
    services, saver, _model, tools, grants = setup
    original = tools.gateway

    def gateway(token, role, trace):
        inner = original(token, role, trace)

        class Gateway:
            async def call(self, name, args):
                if name == "verify_claims":
                    return {"status": "verified", "cleaned_draft": "", "sentences": []}
                return await inner.call(name, args)

        return Gateway()

    services.gateway_factory = gateway
    graph = build_bid_graph(services, checkpointer=saver)
    state = await graph.ainvoke(initial(), {"configurable": {"thread_id": "empty"}})
    assert state["status"] == "needs_attention"
    assert state["errors"]["verify"]["code"] == "empty_verified_draft"
    services.config["budgets"]["max_tokens_per_job"] = 1
    state = await graph.ainvoke(initial(), {"configurable": {"thread_id": "tokens"}})
    assert state["status"] == "needs_attention" and not grants and not tools.receipts
