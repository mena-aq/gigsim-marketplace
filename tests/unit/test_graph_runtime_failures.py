"""Regression cases observed in real CPU graph runs."""

import pytest
from langgraph.types import Command

from agent.execution import NodeContext, review_payload
from agent.graphs.bid_graph import build_bid_graph
from agent.nodes.risk_assessor import risk
from mcp_servers.common.errors import ToolFailure
from mcp_servers.common.security import mask
from tests.unit.test_graphs import initial, setup  # noqa: F401 -- shared fixture


async def test_incomplete_verification_redrafts_with_bounded_revisions(setup):  # noqa: F811
    services, saver, model, tools, grants = setup
    original = tools.gateway

    def gateway(token, role, trace):
        inner = original(token, role, trace)

        class Gateway:
            async def call(self, name, arguments):
                if name == "verify_claims":
                    return {
                        "status": "needs_attention",
                        "cleaned_draft": "",
                        "sentences": [],
                        "diagnostics": {
                            "failures": [{"code": "model_budget_exceeded"}]
                        },
                    }
                return await inner.call(name, arguments)

        return Gateway()

    services.gateway_factory = gateway
    graph = build_bid_graph(services, checkpointer=saver)
    result = await graph.ainvoke(
        initial(), {"configurable": {"thread_id": "verify-failed"}}
    )
    assert result["status"] == "needs_attention"
    assert model.calls.count("writer") == 3
    assert result["verification"]["cover_letter"]["diagnostics"]["failures"]
    assert not grants and not tools.receipts


async def test_user_edits_with_incomplete_verification_never_send(setup):  # noqa: F811
    services, saver, _model, tools, grants = setup
    graph = build_bid_graph(services, checkpointer=saver)
    config = {"configurable": {"thread_id": "edited-unverified"}}
    result = await graph.ainvoke(initial(), config)
    original = tools.gateway

    def gateway(token, role, trace):
        inner = original(token, role, trace)

        class Gateway:
            async def call(self, name, arguments):
                if name == "verify_claims":
                    return {
                        "status": "needs_attention",
                        "cleaned_draft": "",
                        "sentences": [],
                    }
                return await inner.call(name, arguments)

        return Gateway()

    services.gateway_factory = gateway
    result = await graph.ainvoke(
        Command(
            resume={
                "action": "edit",
                "review_hash": review_payload(result)["review_hash"],
                "cover_letter": "I built a forecast.",
            }
        ),
        config,
    )
    assert result["status"] == "needs_attention"
    assert not grants and not tools.receipts


def test_usage_counts_are_visible_while_secret_tokens_stay_masked():
    result = mask(
        {
            "tokens": 100,
            "prompt_tokens": 75,
            "completion_tokens": 25,
            "access_token": "private",
            "tokens_string": "private",
        }
    )
    assert result["tokens"] == 100 and result["prompt_tokens"] == 75
    assert result["access_token"] == result["tokens_string"] == "[REDACTED]"


async def test_no_findings_does_not_produce_an_arbitrary_high_risk(setup):  # noqa: F811
    services, _saver, _model, _tools, _grants = setup
    state = initial(
        job={
            "title": "Forecast",
            "description": "Build a forecast",
            "client_id": "client",
        }
    )
    result = await risk(state, NodeContext(services, state))
    assert (
        result["analyses"]["risk"]["score"]
        == services.config["orchestration"]["risk_levels"]["none"]
    )
    assert not result["analyses"]["risk"]["flags"]


async def test_risk_findings_require_quotes_from_actual_sources(setup):  # noqa: F811
    services, _saver, _model, _tools, _grants = setup

    class Unanchored:
        async def ask(self, role, payload, schema):
            return schema.model_validate(
                {
                    "findings": [
                        {
                            "level": "high",
                            "source": "job",
                            "quote": "invented Telegram request",
                            "reason": "Off-platform",
                        }
                    ]
                }
            ), 10

    services.model = Unanchored()
    state = initial(
        job={
            "title": "Forecast",
            "description": "Build a forecast",
            "client_id": "client",
        }
    )
    with pytest.raises(ToolFailure, match="absent"):
        await risk(state, NodeContext(services, state))


async def test_verifier_coverage_retry_checks_whole_sentence_and_keeps_numeric_guard():
    from rag.types import Chunk
    from rag.verify import verify_claims
    from tests.unit.rag_fakes import FakeLLM

    chunk = Chunk(
        id="source",
        chunk_id="owned",
        persona="ml",
        type="case_study",
        source="case.md",
        source_hash="hash",
        text="I built a Python forecast with 6% MAPE.",
        start=0,
        end=38,
    )
    text = "Previously I built a Python forecast with 6% MAPE."
    partial = {
        "sentences": [
            {
                "index": 0,
                "claims": [
                    {
                        "text": "I built a Python forecast with 6% MAPE.",
                        "kind": "experience",
                        "status": "supported",
                        "evidence_ids": ["E1"],
                        "reason": "Source",
                    }
                ],
            }
        ]
    }
    full = {
        "sentences": [
            {
                "index": 0,
                "claims": [
                    {
                        "text": text,
                        "kind": "experience",
                        "status": "supported",
                        "evidence_ids": ["E1"],
                        "reason": "The whole statement is supported",
                    }
                ],
            }
        ]
    }
    llm = FakeLLM([partial, full])
    report = await verify_claims(text, [chunk], llm)
    assert report.status == "verified" and report.cleaned_draft == text
    assert report.diagnostics["coverage_retries"] == [0]
    assert llm.usage[-1]["prompt"] == "rag_verify_sentence"
    bad = text.replace("6%", "99%")
    from copy import deepcopy

    bad_partial, bad_full = deepcopy(partial), deepcopy(full)
    bad_partial["sentences"][0]["claims"][0]["text"] = (
        "I built a Python forecast with 99% MAPE."
    )
    bad_full["sentences"][0]["claims"][0]["text"] = bad
    rejected = await verify_claims(bad, [chunk], FakeLLM([bad_partial, bad_full]))
    assert not rejected.cleaned_draft
    assert rejected.sentences[0].claims[0].status == "unsupported"


async def test_executor_rejects_a_draft_without_matching_verification(setup):  # noqa: F811
    from agent.nodes.approval import execute

    services, _saver, _model, tools, grants = setup
    state = initial(
        draft={"cover_letter": "Changed after verification", "screening_answers": []},
        verification={
            "cover_letter": {
                "status": "verified",
                "cleaned_draft": "Original checked text",
            }
        },
    )
    with pytest.raises(ToolFailure) as failure:
        await execute(state, NodeContext(services, state))
    assert failure.value.code == "verification_incomplete"
    assert not grants and not tools.receipts


@pytest.mark.parametrize("code", ["connects_reserve", "insufficient_connects"])
async def test_spending_limits_need_attention_instead_of_dead_letter(code):
    from agent.graphs.common import stop

    result = await stop(
        {"errors": {"preview": {"code": code, "message": "Spending limit reached"}}}
    )
    assert result["status"] == "needs_attention"


def test_plain_timeline_estimates_do_not_need_past_experience_citations():
    from rag.verify import plain_nonexperience

    assert plain_nonexperience(
        "I aim to deliver an initial model in two weeks.", "intent"
    )
    assert plain_nonexperience("I estimate two weeks for an initial model.", "intent")
    assert plain_nonexperience("Ready to start within four weeks.", "intent")
    assert not plain_nonexperience("Ready to repeat my previous 99% success.", "intent")
    assert not plain_nonexperience("I aim to repeat my previous 99% success.", "intent")
    assert not plain_nonexperience(
        "I expect to use the model I built for a client.", "intent"
    )
