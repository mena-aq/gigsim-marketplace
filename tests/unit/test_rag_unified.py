"""Unified Part B reporting, historical import, and stage orchestration."""

import csv
import json
import shutil
from types import SimpleNamespace

import pytest

from evals.runners import rag_eval, rag_table
from evals.runners.rag_calibration import calibrate, review_pack
from rag.config import VARIANTS


def write(path, data):
    path.write_text(json.dumps(data) + "\n")


@pytest.fixture
def saved_run(tmp_path):
    folder = tmp_path / "saved"
    folder.mkdir()
    retrieval = {
        "retrieval": {
            "all": {
                v: {
                    "queries": 30,
                    "recall_at_5": 0.8,
                    "ndcg_at_10": 0.7,
                    "mrr": 0.75,
                }
                for v in VARIANTS
            }
        },
        "fingerprint": "historical-retrieval",
    }
    original = folder / "historical_retrieval.jsonl"
    original.write_text('{"kind":"retrieval","fingerprint":"historical-retrieval"}\n')
    retrieval["observations"] = str(original)
    write(folder / "rag_retrieval.json", retrieval)
    shutil.copyfile(original, folder / "rag_retrieval_observations.jsonl")
    arm = {
        "attempted": 30,
        "assessed_proposals": 30,
        "before_unsupported_claims": 6,
        "before_experience_claims": 30,
        "after_unsupported_claims": 0,
        "after_experience_claims": 24,
        "before_unsupported_rate": 0.2,
        "after_unsupported_rate": 0,
        "unsupported_claims_per_proposal": 0,
        "supported_retention_rate": 1,
        "failures": 0,
        "submitted": 30,
        "replies": 9,
        "reply_rate": 0.3,
        "p95_proposal_seconds": 10,
        "total_cost_per_proposal_usd": None,
    }
    write(
        folder / "rag_workflow.json",
        {
            "complete": True,
            "results": {"all": {v: dict(arm) for v in VARIANTS}},
        },
    )
    rows, cases = [], []
    for variant in VARIANTS:
        for i in range(30):
            case_id = f"{variant}-{i}"
            rows.append(
                {
                    "id": case_id,
                    "variant": variant,
                    "persona": f"p{i % 3}",
                    "category": "test",
                    "cleaned_draft": "Draft.",
                    "retrieval": {"hits": []},
                    "judge_score_uncalibrated": i % 5 + 1,
                    "fingerprint": "historical-workflow",
                }
            )
            cases.append(
                {"id": case_id, "job": {"title": "Task", "description": "Build"}}
            )
    (folder / "rag_workflow_observations.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows)
    )
    write(folder / "rag_jobs.json", {"cases": cases})
    write(
        folder / "rag_ablation.json",
        {
            "component_effects": {
                "without_reranker": {"mean_delta": 0.04, "ci95": [0.01, 0.09]},
                "without_bm25": {"mean_delta": 0.01, "ci95": [0, 0.03]},
            }
        },
    )
    review_pack(folder)
    key = {
        r["review_id"]: r
        for r in json.loads((folder / "rag_calibration_key.json").read_text())
    }
    path = folder / "rag_human_review.csv"
    with path.open(newline="") as handle:
        labels = list(csv.DictReader(handle))
    for row in labels:
        # Deliberate low agreement in test fixtures, never published measurements.
        row["human_score"] = key[row["review_id"]]["judge_score"] % 5 + 1
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(labels[0]))
        writer.writeheader()
        writer.writerows(labels)
    calibrate(folder)
    return folder


def test_single_csv_has_exact_b5_columns_and_preserves_low_agreement_scores(
    saved_run, monkeypatch
):
    from rag.llm import StructuredLLM

    async def forbidden(*args, **kwargs):
        raise AssertionError("Offline reporting must not invoke a model")

    monkeypatch.setattr(StructuredLLM, "ask", forbidden)
    labels = (saved_run / "rag_human_review.csv").read_bytes()
    summary = rag_table.write_report(saved_run)
    with (saved_run / "rag_comparison.csv").open(newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == rag_table.FIELDS
        rows = list(reader)
    assert [r["Variant"] for r in rows] == list(VARIANTS)
    assert all(float(r["Judge score"]) == 3 for r in rows)
    assert all(float(r["GigSim reply rate"]) == 0.3 for r in rows)
    assert all(r["Cost per proposal (USD)"] == "" for r in rows)
    assert summary["calibration_current"]
    assert summary["calibration"]["cohens_kappa"] < 0.4
    assert (saved_run / "rag_human_review.csv").read_bytes() == labels
    text = (saved_run / "rag_comparison.md").read_text()
    assert "Component ablation" in text and "0.0400" in text
    assert "6/30 (0.200)" in text and "0/24 (0.000)" in text
    assert summary["sources"]["rag_human_review.csv"]["sha256"] == rag_table.digest(
        saved_run / "rag_human_review.csv"
    )


def test_import_keeps_originals_and_calibration_hashes(saved_run, tmp_path):
    destination = tmp_path / "legacy-results"
    old = destination / "proposal"
    old.mkdir(parents=True)
    mapping = {
        "rag_retrieval.json": "retrieval_snapshot.json",
        "rag_workflow.json": "proposal_summary.json",
        "rag_workflow_observations.jsonl": "proposal_observations.jsonl",
        "rag_jobs.json": "proposal_dataset.json",
        "rag_human_review.csv": "human_review.csv",
        "rag_calibration_key.json": "calibration_key.json",
        "rag_judge_calibration.json": "judge_calibration.json",
    }
    for src, dst in mapping.items():
        shutil.copyfile(saved_run / src, old / dst)
    before = {p.name: p.read_bytes() for p in old.iterdir()}
    rag_table.import_legacy(destination)
    rag_table.import_legacy(destination)  # Idempotent; does not replace labels.
    shutil.copyfile(saved_run / "rag_ablation.json", destination / "rag_ablation.json")
    summary = rag_table.write_report(destination)
    assert before == {p.name: p.read_bytes() for p in old.iterdir()}
    assert summary["calibration_current"]
    assert all(row["Judge score"] == 3 for row in summary["table"])
    assert summary["fingerprint"] == "historical-retrieval"
    imported_rows = (destination / "rag_workflow_observations.jsonl").read_text()
    assert "historical-workflow" in imported_rows


def test_stale_human_scores_are_not_reused(saved_run):
    with (saved_run / "rag_workflow_observations.jsonl").open("a") as handle:
        handle.write("\n")
    # Content changes invalidate calibration even if row semantics are unchanged.
    # Keep JSONL parseable while changing the hash.
    path = saved_run / "rag_workflow_observations.jsonl"
    path.write_text(path.read_text().rstrip() + " \n")
    summary = rag_table.build_summary(saved_run)
    assert not summary["calibration_current"]
    assert all(row["Judge score"] is None for row in summary["table"])


@pytest.mark.parametrize("interrupted", [False, True])
async def test_one_command_runs_all_stages_and_resumes_ablation(
    tmp_path, monkeypatch, interrupted
):
    calls = []
    first_ablation = True

    async def retrieval(args):
        calls.append("retrieval")

    async def workflow(args):
        calls.append("workflow")

    async def ablation(args):
        nonlocal first_ablation
        calls.append("ablation")
        if interrupted and first_ablation:
            first_ablation = False
            raise ValueError("Interrupted")

    async def environment(*args):
        return None

    async def checks(*args):
        return {"passed": True}

    monkeypatch.setattr(rag_eval, "preflight", checks)
    monkeypatch.setattr(rag_eval, "run_fingerprint", lambda args: "test-fingerprint")
    monkeypatch.setattr(rag_eval, "capture_environment", environment)
    monkeypatch.setattr(rag_eval.rag_retrieval, "run", retrieval)
    monkeypatch.setattr(rag_eval.rag_workflow, "run", workflow)
    monkeypatch.setattr(rag_eval.rag_ablation, "main_async", ablation)
    monkeypatch.setattr(rag_eval, "review_pack", lambda folder: {"status": "pending"})
    monkeypatch.setattr(
        rag_table, "write_report", lambda folder, **kw: calls.append(("report", kw))
    )
    args = SimpleNamespace(
        output_dir=tmp_path,
        limit=0,
        variants=list(VARIANTS),
        retrieval_dataset=tmp_path / "queries.json",
        jobs_dataset=tmp_path / "jobs.json",
    )
    if interrupted:
        with pytest.raises(ValueError, match="Interrupted"):
            await rag_eval.run(args)
    await rag_eval.run(args)
    assert calls[:3] == ["retrieval", "workflow", "ablation"]
    assert calls.count("retrieval") == 1 and calls.count("workflow") == 1
    assert calls.count("ablation") == (2 if interrupted else 1)
    assert calls[-1] == ("report", {"publish": True, "update_readme": True})
    calls.clear()
    await rag_eval.run(args)
    assert calls == [("report", {"publish": True, "update_readme": True})]
    monkeypatch.setattr(rag_eval, "run_fingerprint", lambda args: "changed")
    with pytest.raises(ValueError, match="Cannot resume"):
        await rag_eval.run(args)
