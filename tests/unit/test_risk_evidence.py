"""Risk findings must be grounded in the job or client history, without being brittle."""

from types import SimpleNamespace

import pytest

from agent.config import load_graph_config
from agent.nodes.risk_assessor import risk, squash
from mcp_servers.common.errors import ToolFailure

HISTORY = {
    "client": {"payment_verified": True, "hire_rate": 0.9, "name": "Aurora"},
    "reviews": ['Said "no refunds" twice.'],
    "proposals_received": 3,
}


def context(findings):
    async def tool(role, name, arguments):
        return HISTORY

    async def ask(role, payload, schema):
        return {"findings": findings}

    return SimpleNamespace(config=load_graph_config(), tool=tool, ask=ask)


def state(description):
    return {
        "job": {
            "title": "RAG Specialist",
            "description": description,
            "client_id": "c1",
            "screening_questions": ["Why you?"],
        }
    }


def finding(quote, source="job", level="caution"):
    return {"level": level, "source": source, "quote": quote, "reason": "because"}


async def test_quote_with_repaired_spacing_is_accepted():
    # The post glues sentences together; the model quotes them with a space.
    job = state("Set up a RAG system.This system should use more than 1 pdf file.")
    result = await risk(
        job, context([finding("RAG system. This system should use more than 1 PDF")])
    )
    report = result["analyses"]["risk"]
    assert report["score"] == 0.5 and report["flags"] == ["because"]


async def test_fabricated_quote_still_fails_closed():
    job = state("Build a chatbot for our shop.")
    with pytest.raises(ToolFailure, match="absent"):
        await risk(job, context([finding("send payment to my bank", level="high")]))


async def test_one_fabricated_finding_fails_even_next_to_a_real_one():
    job = state("Pay is unpaid trial work first.")
    findings = [
        finding("unpaid trial work", level="high"),
        finding("totally invented", level="high"),
    ]
    with pytest.raises(ToolFailure, match="absent"):
        await risk(job, context(findings))


async def test_history_quotes_match_plain_text_not_json_escapes():
    job = state("Build a chatbot.")
    result = await risk(
        job, context([finding('Said "no refunds" twice.', source="history")])
    )
    assert result["analyses"]["risk"]["flags"] == ["because"]


def test_squash_ignores_whitespace_and_case_only():
    assert squash("A  b\nC") == squash("a B c")
    assert squash("abc") != squash("abd")
