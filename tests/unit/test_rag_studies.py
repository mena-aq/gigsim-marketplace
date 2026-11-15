"""Small synthetic correctness fixtures; no real studies or model calls run here."""

import json
from types import SimpleNamespace

import httpx
import pytest

from evals.runners.rag_ablation import (
    CONFIGURATIONS,
    NoGeneration,
    analyze_rows,
    run_configuration,
)
from evals.runners.rag_rd_b import analyze
from evals.runners.rag_rd_b import main as hypothesis_main
from evals.runners.rag_study import StudyError, bootstrap, load_dataset, load_pairs
from rag.types import Chunk, Hit


@pytest.fixture
def study(tmp_path):
    queries = [
        {
            "id": "q1",
            "persona": "ml",
            "type": "direct",
            "query": "python",
            "qrels": {"a": 2},
        },
        {
            "id": "q2",
            "persona": "web",
            "type": "multi",
            "query": "React",
            "qrels": {"b": 2},
        },
        {
            "id": "q3",
            "persona": "ml",
            "type": "none",
            "query": "no evidence",
            "qrels": {},
        },
    ]
    dataset = {"reviewed_by_user": False, "queries": queries}
    rows = []
    for query in queries:
        gold = list(query["qrels"])
        for variant in ("v2", "v3"):
            ids = (gold + ["x"] if variant == "v3" else ["x"] + gold) if gold else ["x"]
            rows.append(
                {
                    "kind": "retrieval",
                    "id": query["id"],
                    "persona": query["persona"],
                    "query_type": query["type"],
                    "variant": variant,
                    "returned_ids": ids,
                    "seconds": 2.0 if variant == "v2" else 3.0,
                    "error": None,
                    "metrics": {"ndcg_at_10": 999},
                    "fingerprint": "one-source-run",
                }
            )
    dataset_path = tmp_path / "dataset.json"
    run = tmp_path / "run.jsonl"
    dataset_path.write_text(json.dumps(dataset))

    def save():
        run.write_text("".join(json.dumps(row) + "\n" for row in rows))

    save()
    return SimpleNamespace(
        dataset=dataset,
        rows=rows,
        dataset_path=dataset_path,
        run=run,
        save=save,
        output=tmp_path / "reports",
    )


def test_offline_hypothesis_pairs_rescores_and_excludes_negative_queries(study):
    summary, pairs, dataset = analyze(study.run, study.dataset_path, samples=200)
    result = summary["primary_result"]
    assert result["pairs"] == 2
    assert result["mean_delta"] == pytest.approx(1 - 1 / 1.584962500721156)
    assert result["ci95"][0] > 0
    assert result["outcome"] == "observed_improvement"
    assert summary["breakdowns"]["all"]["v3"]["queries"] == 3
    assert summary["breakdowns"]["all"]["v3"]["ndcg_at_10"] == 1
    assert pairs[2]["delta_ndcg_at_10"] is None
    assert dataset["reviewed_by_user"] is False


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "duplicate",
        "mixed_fingerprint",
        "persona",
        "type",
        "unknown_query",
        "invalid_latency",
        "duplicate_ranking",
    ],
)
def test_mismatched_or_incomplete_saved_measurements_are_rejected(study, change):
    if change == "missing":
        study.rows.pop()
    elif change == "duplicate":
        study.rows.append(dict(study.rows[0]))
    elif change == "mixed_fingerprint":
        study.rows[0]["fingerprint"] = "other-run"
    elif change == "persona":
        study.rows[0]["persona"] = "other"
    elif change == "type":
        study.rows[0]["query_type"] = "other"
    elif change == "unknown_query":
        study.rows[0]["id"] = "other"
    elif change == "invalid_latency":
        study.rows[0]["seconds"] = float("nan")
    else:
        study.rows[0]["returned_ids"] = ["a", "a"]
    study.save()
    with pytest.raises(StudyError):
        load_pairs(study.run, load_dataset(study.dataset_path))


def test_environment_sidecar_fingerprint_must_match(study):
    study.run.with_suffix(".environment.json").write_text(
        json.dumps({"observation_fingerprint": "different"})
    )
    with pytest.raises(StudyError, match="sidecar"):
        analyze(study.run, study.dataset_path, samples=100)


def test_failures_are_zero_quality_not_dropped(study):
    study.rows[1]["error"] = {"code": "failed"}
    study.save()
    summary, _, _ = analyze(study.run, study.dataset_path, samples=100)
    assert summary["primary_result"]["pairs"] == 2
    assert summary["breakdowns"]["all"]["v3"]["failures"] == 1
    assert summary["breakdowns"]["all"]["v3"]["ndcg_at_10"] == 0.5


def test_zero_grade_labels_are_not_recall_denominator_entries(study):
    study.dataset["queries"][0]["qrels"]["irrelevant"] = 0
    study.dataset_path.write_text(json.dumps(study.dataset))
    summary, _, _ = analyze(study.run, study.dataset_path, samples=100)
    assert summary["breakdowns"]["all"]["v3"]["recall_at_5"] == 1


def test_hypothesis_command_writes_reports_without_services(study, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline analysis must not open a network client")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    hypothesis_main(
        [
            "--run",
            str(study.run),
            "--dataset",
            str(study.dataset_path),
            "--output-dir",
            str(study.output),
        ]
    )
    for suffix in (".json", ".csv", ".md", "_queries.jsonl", "_dataset.json"):
        assert (study.output / ("rag_rd_b" + suffix)).is_file()
    result = json.loads((study.output / "rag_rd_b.json").read_text())
    assert result["source_fingerprint"] == "one-source-run"
    assert (
        "No-evidence queries are excluded" in (study.output / "rag_rd_b.md").read_text()
    )


def test_paired_bootstrap_is_reproducible_and_reports_ties():
    pairs = [
        {"positive": True, "persona": "ml", "delta_ndcg_at_10": value}
        for value in (-0.2, 0, 0.2, 0.4)
    ]
    assert bootstrap(pairs, 1000, 42) == bootstrap(pairs, 1000, 42)
    assert bootstrap(pairs, 1000, 42)["mean_delta"] == pytest.approx(0.1)
    tied = [{**pair, "delta_ndcg_at_10": 0} for pair in pairs]
    assert bootstrap(tied, 100, 42)["outcome"] == "no_observed_difference"


class ToyPipeline:
    def __init__(self):
        self.config = SimpleNamespace(candidate_k=2, rrf_constant=60)
        self.filtered_chunks = [
            self.chunk("a", "alpha"),
            self.chunk("b", "beta"),
            self.chunk("c", "needle"),
        ]
        self.dense_limits = []
        self.reranked_texts = []
        self.diagnostics = {}
        self.manifest = {"user_id": "toy", "records": []}
        self.prepared = False

    @staticmethod
    def chunk(key, text):
        return Chunk(
            id="doc-" + key,
            persona="ml",
            type="case_study",
            source=key + ".md",
            source_hash="hash",
            text=text,
            chunk_id=key,
            start=0,
            end=len(text),
        )

    async def prepare(self):
        self.prepared = True

    async def dense(self, query, k):
        self.dense_limits.append(k)
        return [Hit(chunk=chunk, score=1.0) for chunk in self.filtered_chunks[:2]][:k]

    def rerank(self, query, texts):
        self.reranked_texts.append(list(texts))
        return [{"alpha": 1, "beta": 3, "needle": 2}[text] for text in texts]


async def test_ablation_removes_only_the_target_component():
    full, without_ranker, without_bm25 = ToyPipeline(), ToyPipeline(), ToyPipeline()
    a = await run_configuration("needle", full, "full_v3")
    b = await run_configuration("needle", without_ranker, "without_reranker")
    c = await run_configuration("needle", without_bm25, "without_bm25")
    assert a["returned_ids"] == ["doc-c", "doc-a"]
    assert b["returned_ids"] == ["doc-a", "doc-c"]
    assert c["returned_ids"] == ["doc-b", "doc-a"]
    assert full.reranked_texts == [["alpha", "needle"]]
    assert without_ranker.reranked_texts == []
    assert without_bm25.reranked_texts == [["alpha", "beta"]]
    assert (
        full.dense_limits
        == without_ranker.dense_limits
        == without_bm25.dense_limits
        == [2]
    )


async def test_ablation_refuses_changed_index_and_unknown_configuration():
    pipeline = ToyPipeline()
    with pytest.raises(StudyError, match="Index changed"):
        await run_configuration(
            "needle", pipeline, "full_v3", expected_manifest="wrong"
        )
    assert pipeline.dense_limits == []
    with pytest.raises(StudyError, match="Unknown"):
        await run_configuration("needle", pipeline, "v9")


async def test_generation_guard_never_calls_a_model():
    with pytest.raises(StudyError, match="forbidden"):
        await NoGeneration().ask("anything", {}, None)


def test_ablation_summary_requires_complete_pairs(study):
    rows = []
    for query in study.dataset["queries"]:
        for setting in CONFIGURATIONS:
            rows.append(
                {
                    "id": query["id"],
                    "persona": query["persona"],
                    "query_type": query["type"],
                    "configuration": setting,
                    "returned_ids": list(query["qrels"]),
                    "error": None,
                    "seconds": 1,
                    "fingerprint": "same",
                }
            )
    summary = analyze_rows(rows, study.dataset)
    assert summary["generative_model_calls"] == 0
    assert summary["component_effects"]["without_bm25"]["mean_delta"] == 0
    with pytest.raises(StudyError, match="one observation"):
        analyze_rows(rows[:-1], study.dataset)


def test_failed_negative_query_is_not_successful_abstention(study):
    study.rows[-1]["returned_ids"] = []
    study.rows[-1]["error"] = {"code": "timeout"}
    study.save()
    summary, _, _ = analyze(study.run, study.dataset_path, samples=100)
    assert summary["breakdowns"]["all"]["v3"]["correct_abstention"] == 0
    assert summary["primary_result"]["pairs"] == 2


def test_ablation_rejects_mixed_run_fingerprints(study):
    rows = [
        {
            "id": query["id"],
            "persona": query["persona"],
            "query_type": query["type"],
            "configuration": setting,
            "returned_ids": list(query["qrels"]),
            "error": None,
            "seconds": 1,
            "fingerprint": "same",
        }
        for query in study.dataset["queries"]
        for setting in CONFIGURATIONS
    ]
    rows[0]["fingerprint"] = "different"
    with pytest.raises(StudyError, match="fingerprint"):
        analyze_rows(rows, study.dataset)
