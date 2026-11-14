"""Risk findings must be grounded in the job or client history, without being brittle."""

from types import SimpleNamespace

from agent.config import load_graph_config
from agent.nodes.risk_assessor import risk, squash

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
    assert report["score"] == 0.5 and report["ignored_findings"] == []
    assert report["flags"] == ["because"]


async def test_fabricated_quote_is_ignored_not_fatal():
    job = state("Build a chatbot for our shop.")
    result = await risk(
        job, context([finding("send payment to my bank", level="high")])
    )
    report = result["analyses"]["risk"]
    assert report["score"] == 0.1  # a made-up finding adds no risk
    assert report["flags"] == [] and report["findings"] == []
    assert report["ignored_findings"][0]["quote"] == "send payment to my bank"


async def test_history_quotes_match_plain_text_not_json_escapes():
    job = state("Build a chatbot.")
    result = await risk(
        job, context([finding('Said "no refunds" twice.', source="history")])
    )
    assert result["analyses"]["risk"]["ignored_findings"] == []


async def test_grounded_and_ungrounded_findings_are_separated():
    job = state("Pay is unpaid trial work first.")
    result = await risk(
        job,
        context(
            [
                finding("unpaid trial work", level="high"),
                finding("totally invented", level="high"),
            ]
        ),
    )
    report = result["analyses"]["risk"]
    assert report["score"] == 0.9
    assert [f["quote"] for f in report["findings"]] == ["unpaid trial work"]
    assert [f["quote"] for f in report["ignored_findings"]] == ["totally invented"]


def test_squash_ignores_whitespace_and_case_only():
    assert squash("A  b\nC") == squash("a B c")
    assert squash("abc") != squash("abd")
