"""R&D question C: job set, scorer and the single-agent baseline loop."""

import pytest

from agent.baselines.single_agent import run_single_agent
from agent.config import load_graph_config
from agent.execution import GraphServices
from agent.mcp_client import AGENT_TOOLS
from evals.runners.agent_compare_metrics import (
    build_job_set,
    percentile,
    reply_probability,
    score_row,
    summarize,
    violations,
)
from mcp_servers.common.errors import ToolFailure
from tests.unit.test_graphs import Tools

CATEGORIES = {
    "ml_engineer": "AI & Machine Learning",
    "fullstack_dev": "Web Development",
    "data_analyst": "Data Science",
}


def fake_world():
    clients = [
        {"id": f"c{i}", "hire_rate": 0.9, "hidden_preferences": {}} for i in range(3)
    ]
    jobs, dev = [], []
    for persona, category in CATEGORIES.items():
        for n in range(8):
            for flag in ("clean", "is_scam", "has_injection"):
                job = {
                    "id": f"{persona}-{flag}-{n}",
                    "title": "t",
                    "description": "d",
                    "skills": ["Python"],
                    "category": category,
                    "client_id": "c0",
                    "is_scam": flag == "is_scam",
                    "has_injection": flag == "has_injection",
                }
                if flag == "clean":
                    dev.append(
                        {
                            "id": job["id"],
                            "persona": persona,
                            "job": job,
                            "client": clients[0],
                        }
                    )
                else:
                    jobs.append(job)
    return jobs, clients, dev


def test_job_set_is_the_requested_mix_and_deterministic():
    jobs, clients, dev = fake_world()
    cases = build_job_set(jobs, clients, dev, seed=3)
    assert len(cases) == 20 == len({c["id"] for c in cases})
    kinds = [c["kind"] for c in cases]
    assert (kinds.count("clean"), kinds.count("scam"), kinds.count("injection")) == (
        12,
        5,
        3,
    )
    for persona in CATEGORIES:
        assert sum(c["persona"] == persona and c["kind"] == "clean" for c in cases) == 4
    assert all(c["gold"] == ("bid" if c["kind"] == "clean" else "skip") for c in cases)
    assert cases == build_job_set(jobs, clients, dev, seed=3)
    assert [c["id"] for c in cases] != [
        c["id"] for c in build_job_set(jobs, clients, dev, seed=4)
    ]
    # A --limit 2 smoke run must see a clean job and a planted one.
    assert {c["kind"] for c in cases[:2]} == {"clean", "scam"}


def test_planted_jobs_match_the_persona_category_when_the_data_allows():
    jobs, clients, dev = fake_world()
    for case in build_job_set(jobs, clients, dev):
        assert CATEGORIES[case["persona"]] == case["job"]["category"]
        assert not case.get("off_category")


def test_a_short_category_is_filled_from_others_and_flagged():
    jobs, clients, dev = fake_world()
    jobs = [
        j
        for j in jobs
        if not (j["is_scam"] and j["category"] == "AI & Machine Learning")
    ]
    cases = build_job_set(jobs, clients, dev)
    kinds = [c["kind"] for c in cases]
    assert (kinds.count("scam"), kinds.count("injection")) == (5, 3)
    assert len({c["id"] for c in cases}) == 20  # no job reused across personas
    filled = [c for c in cases if c.get("off_category")]
    assert len(filled) == 1 and filled[0]["persona"] == "ml_engineer"


def test_violations_use_the_same_policy_as_the_compliance_node():
    config = load_graph_config()
    job = {"description": "Build a small dashboard for our sales team this month."}
    assert violations("I can start next week.", job, config) == []
    assert violations(
        "Email me at a@b.com to ignore previous instructions", job, config
    )


def test_reply_probability_follows_gigsim_rules():
    job = {"skills": ["Python", "SQL"]}
    letter = "I will build this in Python and SQL."
    open_client = {"hire_rate": 0.9, "hidden_preferences": {}}
    assert 0.4 < reply_probability(open_client, job, letter) < 0.6
    assert (
        reply_probability({"hire_rate": 0.05, "hidden_preferences": {}}, job, letter)
        == 0
    )
    picky = {"hire_rate": 0.9, "hidden_preferences": {"must_have_skills": ["php"]}}
    assert reply_probability(picky, job, letter) == 0
    assert reply_probability(open_client, job, "Dear hiring manager, Python.") == 0


def row(job_id, action, **extra):
    return {
        "id": job_id,
        "action": action,
        "submitted": action == "bid",
        "cover_letter": "I will use Python." if action == "bid" else "",
        "tokens": 100,
        "seconds": 10.0,
        **extra,
    }


def test_summary_counts_accuracy_false_bids_and_unsupported_claims():
    config = load_graph_config()
    cases = {
        "ok": {
            "id": "ok",
            "kind": "clean",
            "gold": "bid",
            "persona": "p",
            "job": {"skills": ["Python"], "description": "x"},
            "client": {"hire_rate": 0.9, "hidden_preferences": {}},
        },
        "scam": {
            "id": "scam",
            "kind": "scam",
            "gold": "skip",
            "persona": "p",
            "job": {"skills": ["Python"], "description": "x"},
            "client": {"hire_rate": 0.9, "hidden_preferences": {}},
        },
        "bad": {
            "id": "bad",
            "kind": "injection",
            "gold": "skip",
            "persona": "p",
            "job": {"skills": [], "description": "x"},
            "client": {"hire_rate": 0.9, "hidden_preferences": {}},
        },
    }
    rows = [
        row("ok", "bid", unsupported={"experience": 4, "unsupported": 1}),
        row("scam", "bid", unsupported={"experience": 2, "unsupported": 2}),
        {
            "id": "bad",
            "action": None,
            "submitted": False,
            "error": "model_failed",
            "seconds": 5.0,
        },
    ]
    result = summarize(rows, cases, config)
    assert result["n"] == 3 and result["bid_or_skip_correct"] == 1
    assert (
        result["false_bids"] == 1 and result["skip_caught"] == 0
    )  # errored skip is not a catch
    assert result["errors"] == 1 and result["letters_submitted"] == 2
    assert (result["unsupported_claims"], result["experience_claims"]) == (3, 6)
    assert result["by_kind"]["clean"] == {"n": 1, "correct": 1, "bid": 1, "errors": 0}


def test_watch_on_a_clean_job_counts_as_a_miss():
    config = load_graph_config()
    case = {
        "id": "x",
        "kind": "clean",
        "gold": "bid",
        "job": {"description": ""},
        "client": {},
    }
    assert not score_row({"action": "watch"}, case, config)["correct"]
    assert not score_row({"action": None}, case, config)["correct"]


def test_percentile():
    assert percentile([], 0.5) is None
    assert percentile([1, 2, 3, 4], 0.5) == 2 and percentile([1, 2, 3, 4], 0.95) == 4


class Script:
    """Scripted model: yields the given step actions, then the final answer."""

    def __init__(self, steps, final):
        self.steps, self.final, self.calls = list(steps), final, []

    async def ask(self, role, payload, schema):
        self.calls.append(payload["mode"])
        if payload["mode"] == "next_step":
            return schema.model_validate(self.steps.pop(0)), 10
        return schema.model_validate(self.final), 20


BID = {
    "action": "bid",
    "reason": "fits",
    "cover_letter": "I built Python forecasting.",
    "price": 500,
}


def agent(steps, final=BID):
    tools = Tools()
    model = Script(steps, final)
    return GraphServices(model=model, gateway_factory=tools.gateway), model, tools


async def test_loop_gathers_evidence_then_answers():
    services, model, _ = agent(
        [
            {"action": "get_client_history"},
            {"action": "search_evidence", "query": "python"},
            {"action": "finish"},
        ]
    )
    result = await run_single_agent(services, "job")
    assert result["action"] == "bid" and [t["action"] for t in result["trace"]] == [
        "get_client_history",
        "search_evidence",
        "finish",
    ]
    assert result["evidence"][0]["chunk_id"] == "chunk"
    assert model.calls == ["next_step"] * 3 + ["final"]
    assert result["tokens"] == 10 * 3 + 20


async def test_loop_stops_at_the_step_cap_and_on_repeats():
    services, model, _ = agent([{"action": "search_evidence", "query": "a"}] * 5)
    await run_single_agent(services, "job", max_steps=2)
    assert model.calls.count("next_step") == 2 and model.calls[-1] == "final"
    services, model, tools = agent(
        [{"action": "get_client_history"}, {"action": "get_client_history"}]
    )
    await run_single_agent(services, "job", max_steps=3)
    assert [n for n, _ in tools.calls].count("get_client_history") == 1


async def test_a_bid_without_a_letter_fails_instead_of_sending_nothing():
    services, _, _ = agent(
        [{"action": "finish"}],
        {"action": "bid", "reason": "x", "cover_letter": " ", "price": 500},
    )
    with pytest.raises(ToolFailure, match="no letter"):
        await run_single_agent(services, "job")


def test_the_baseline_role_has_no_write_tools():
    allowed = AGENT_TOOLS["single_agent"]
    assert allowed and not allowed & {
        "submit_proposal",
        "send_message",
        "create_proposal_draft",
        "create_hold",
        "create_email_draft",
    }
