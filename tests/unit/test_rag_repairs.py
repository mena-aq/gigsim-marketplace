"""Regression tests for embedding budgets, grounded selection, and coherent fixtures."""

import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from data.client_matching import (
    assign_clients,
    ensure_client_coverage,
    job_skills,
    required_skills,
)
from data.scripts.repair_client_assignments import repair
from evals.runners.rag_diagnostics import failure_diagnostics
from evals.runners.rag_preflight import validate_pairs
from rag.models import Embeddings
from rag.types import Chunk, RagFailure
from rag.variants.v1_decomposed import retrieve
from rag.verify import verify_claims
from tests.unit.rag_fakes import FakeLLM
from tests.unit.rag_fakes import test_config as make_config


def mock_embedding_http(monkeypatch, callback):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        "rag.models.httpx.AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(callback), **kwargs),
    )
    monkeypatch.setattr("rag.models.asyncio.sleep", AsyncMock())


async def test_embedding_boundary_and_no_permanent_error_retry(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        assert body["truncate"] is False
        return httpx.Response(200, json={"embeddings": [[1.0] + [0.0] * 15]})

    mock_embedding_http(monkeypatch, respond)
    embeddings = Embeddings(config)
    assert len(await embeddings.embed(["python " * 254])) == 1
    with pytest.raises(RagFailure) as error:
        await embeddings.embed(["python " * 255])
    assert (
        error.value.code == "embedding_context_exceeded" and not error.value.retryable
    )
    assert len(requests) == 1


@pytest.mark.parametrize(
    "status,code,calls",
    [(400, "embedding_context_exceeded", 1), (503, "embedding_http_error", 2)],
)
async def test_embedding_http_failures_classified(
    tmp_path, monkeypatch, status, code, calls
):
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(
            status,
            json={
                "error": "the input length exceeds the context length"
                if status == 400
                else "unavailable"
            },
        )

    mock_embedding_http(monkeypatch, respond)
    with pytest.raises(RagFailure) as error:
        await Embeddings(make_config(tmp_path)).embed(["python"])
    assert error.value.code == code and len(seen) == calls
    assert error.value.retryable == (status == 503)


async def test_embedding_transient_retry_recovers(tmp_path, monkeypatch):
    seen = []

    def respond(request):
        seen.append(request)
        return (
            httpx.Response(503)
            if len(seen) == 1
            else httpx.Response(200, json={"embeddings": [[1.0] + [0.0] * 15]})
        )

    mock_embedding_http(monkeypatch, respond)
    assert len(await Embeddings(make_config(tmp_path)).embed(["python"])) == 1
    assert len(seen) == 2


async def test_runtime_limit_honors_model_parameter_over_architecture(
    tmp_path, monkeypatch
):
    mock_embedding_http(
        monkeypatch,
        lambda req: httpx.Response(
            200,
            json={
                "model_info": {"bert.context_length": 512},
                "parameters": "num_ctx 256\n",
            },
        ),
    )
    config = make_config(tmp_path)
    assert await Embeddings(config).validate_runtime() == 256
    with pytest.raises(RagFailure) as error:
        await Embeddings(
            config.model_copy(update={"embedding_context_tokens": 512})
        ).validate_runtime()
    assert error.value.code == "embedding_context_mismatch"


async def test_source_selection_reconstructs_exact_text_and_rejects_foreign_ids():
    query = "Build a Python API.\nUse PostgreSQL."
    dense = AsyncMock(return_value=[])
    context = SimpleNamespace(
        llm=FakeLLM([{"ids": ["R2"]}]),
        config=SimpleNamespace(max_requirements=6, rrf_constant=60),
        diagnostics={},
        dense=dense,
    )
    await retrieve(query, context, 5)
    dense.assert_awaited_once_with("Use PostgreSQL.", 5)
    assert context.diagnostics["requirements"] == ["Use PostgreSQL."]
    context.llm = FakeLLM([{"ids": ["R999"]}])
    with pytest.raises(RagFailure, match="anchored"):
        await retrieve(query, context, 5)


async def test_one_invalid_fact_does_not_erase_good_fact_or_plain_intentions():
    chunk = Chunk(
        id="one",
        persona="ml",
        type="case_study",
        source="case.md",
        source_hash="hash",
        text="I built Python.",
        chunk_id="proof",
        start=0,
        end=15,
    )

    def answer(index, text, citation):
        return {
            "sentences": [
                {
                    "index": index,
                    "claims": [
                        {
                            "text": text,
                            "kind": "experience",
                            "status": "supported",
                            "evidence_ids": [citation],
                            "reason": "test",
                        }
                    ],
                }
            ]
        }

    llm = FakeLLM(
        [answer(0, "I built Rust.", "E99"), answer(1, "I built Python.", "E1")]
    )
    draft = (
        "I built Rust. I built Python. I will deliver a plan. What is your deadline?"
    )
    report = await verify_claims(draft, [chunk], llm)
    assert (
        report.cleaned_draft
        == "I built Python.\nI will deliver a plan.\nWhat is your deadline?"
    )
    assert report.status == "needs_attention"
    assert len(llm.usage) == 2 and len(report.diagnostics["failures"]) == 1
    assert all(s.text == draft[s.start : s.end] for s in report.sentences)


def client(id="client", skills=None, bad=False):
    return {
        "id": id,
        "name": "Synthetic",
        "hire_rate": 0.05 if bad else 0.8,
        "total_spend": 1000,
        "avg_rating": 4.5,
        "payment_verified": not bad,
        "is_bad_actor": bad,
        "hidden_preferences": {
            "must_have_skills": skills or ["marketing"],
            "budget_ceiling": 1000,
            "dislikes": [],
        },
        "reviews": [],
    }


def test_assignment_covers_missing_skills_is_seeded_and_keeps_bad_actors():
    jobs = [
        {"id": "one", "category": "Data Science", "skills": ["Python", "SQL"]},
        {"id": "two", "category": "Data Science", "skills": ["Python", "SQL"]},
    ]
    clients = [client(bad=True)]
    original = copy.deepcopy(clients[0])
    added = ensure_client_coverage(jobs, clients)
    assert len(added) == 1 and clients[0] == original
    first = copy.deepcopy(jobs)
    assign_clients(jobs, clients, 42)
    assign_clients(first, clients, 42)
    assert jobs == first
    lookup = {c["id"]: c for c in clients}
    assert all(job_skills(j) & required_skills(lookup[j["client_id"]]) for j in jobs)
    # A compatible bad actor remains in the candidate population.
    only_bad = [client(skills=["Python"], bad=True)]
    assign_clients(jobs, only_bad)
    assert all(j["client_id"] == "client" for j in jobs)


def test_repair_preserves_public_jobs_original_profiles_and_old_snapshot(tmp_path):
    source, output = tmp_path / "source", tmp_path / "repaired"
    source.mkdir()
    jobs = [
        {
            "id": "one",
            "category": "Data Science",
            "skills": ["Python", "SQL"],
            "title": "Build",
            "description": "Build an API",
            "client_id": "c0",
        }
    ]
    clients = [client(f"c{i}", bad=i == 0) for i in range(20)]
    for name, data in [
        ("jobs.json", jobs),
        ("stream_jobs.json", []),
        ("clients.json", clients),
    ]:
        (source / name).write_text(json.dumps(data))
    benchmark = tmp_path / "old.json"
    benchmark.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "one",
                        "persona": "ml_engineer",
                        "job": jobs[0],
                        "client": clients[0],
                    }
                ]
            }
        )
    )
    original = {p: p.read_bytes() for p in [*source.iterdir(), benchmark]}
    snapshot = tmp_path / "v2.json"
    report = repair(source, output, benchmark, snapshot)
    assert report["added_clients"] == 1
    assert all(p.read_bytes() == value for p, value in original.items())
    new = json.loads(snapshot.read_text())["cases"][0]
    assert {k: v for k, v in new["job"].items() if k != "client_id"} == {
        k: v for k, v in jobs[0].items() if k != "client_id"
    }
    repaired_clients = json.loads((output / "clients.json").read_text())
    assert repaired_clients[:20] == clients
    assert validate_pairs([new])["compatible_pairs"] == 1
    assert repair(source, output, benchmark, snapshot) == report
    with pytest.raises(ValueError, match="new output"):
        repair(source, source, benchmark, snapshot)


def test_preflight_rejects_the_original_mismatched_fixture():
    case = {
        "id": "one",
        "job": {"skills": ["Python"]},
        "client": client(skills=["PHP"]),
    }
    with pytest.raises(ValueError, match="incompatible"):
        validate_pairs([case])


def test_diagnostics_explain_old_zero_replies_without_changing_rows():
    case = {"job": {"skills": ["Python"]}, "client": client(skills=["PHP"])}
    rows = [
        {
            "id": "one",
            "cleaned_draft": "I will use Python.",
            "outcome": {"submitted": True, "status": "no_reply"},
        }
    ]
    original = copy.deepcopy(rows)
    report = failure_diagnostics(rows, {"one": case})
    assert report["reply_gate_counts"] == {"skill_mismatch": 1}
    assert rows == original


@pytest.mark.parametrize(
    "mode,code,retries",
    [
        ("timeout", "model_timeout", 2),
        ("http400", "model_http_error", 1),
        ("schema", "model_response_invalid", 2),
    ],
)
async def test_structured_model_failures_are_distinct_and_bounded(
    tmp_path, monkeypatch, mode, code, retries
):
    from evals.runners.rag_workflow import JudgeScore
    from rag.llm import StructuredLLM

    seen = []

    def respond(request):
        seen.append(request)
        if mode == "timeout":
            raise httpx.ReadTimeout("test", request=request)
        if mode == "http400":
            return httpx.Response(400)
        return httpx.Response(200, json={"message": {"content": "not JSON"}})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        "rag.llm.httpx.AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    monkeypatch.setattr("rag.llm.asyncio.sleep", AsyncMock())
    with pytest.raises(RagFailure) as error:
        await StructuredLLM(make_config(tmp_path)).ask(
            "rag_eval_judge", {"proposal": "Test"}, JudgeScore
        )
    assert error.value.code == code and len(seen) == retries


async def test_preflight_controls_do_not_modify_benchmark_or_count_as_results(
    tmp_path, monkeypatch
):
    from evals.runners import rag_preflight

    case = {
        "id": "one",
        "job": {"skills": ["Python"]},
        "client": client(skills=["Python"]),
    }
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"cases": [case]}))
    original = path.read_bytes()

    class RuntimeEmbeddings:
        def __init__(self, config):
            self.config = config

        async def validate_runtime(self):
            return 256

        async def embed(self, texts):
            assert texts == ["python " * 254]
            return [[1.0] + [0.0] * 15]

    calls = []

    async def outcome(control, draft, seed):
        calls.append((copy.deepcopy(control), draft, seed))
        mismatch = control["client"]["hidden_preferences"]["must_have_skills"] == [
            "unrelated-control-skill"
        ]
        return {"status": "no_reply" if mismatch else "replied", "reply": not mismatch}

    monkeypatch.setattr(rag_preflight, "Embeddings", RuntimeEmbeddings)
    monkeypatch.setattr(rag_preflight, "simulate_outcome", outcome)
    report = await rag_preflight.preflight(make_config(tmp_path), path)
    assert report["passed"] and len(calls) == 2
    assert path.read_bytes() == original and calls[0][2] == calls[1][2] == 42
    assert report["controls"] == {
        "seed": 42,
        "matching": "replied",
        "mismatched": "no_reply",
    }
