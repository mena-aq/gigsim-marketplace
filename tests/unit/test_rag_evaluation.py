"""Regression and measurement tests; fake inference never supplies published numbers."""

import json

import pytest

from evals.runners.rag_calibration import agreement, calibrate
from evals.runners.rag_outcomes import simulate_outcome
from evals.runners.rag_workflow import claim_counts, summarize
from rag.config import ROOT
from rag.verify import verify_claims
from tests.unit.rag_fakes import FakeLLM


def judgment(text, kind="nonfactual", status="unsupported", ids=None):
    return {
        "sentences": [
            {
                "index": 0,
                "claims": [
                    {
                        "text": text,
                        "kind": kind,
                        "status": status,
                        "evidence_ids": ids or [],
                        "reason": "regression",
                    }
                ],
            }
        ]
    }


@pytest.mark.parametrize(
    "text,kind,status",
    [
        ("I achieved an AUC-ROC of 1.0.", "nonfactual", "unsupported"),
        ("I reduced reporting time to two seconds.", "nonfactual", "supported"),
        ("I built a Rust backend.", "intent", "supported"),
        ("I will use Python because I built ten systems.", "intent", "supported"),
    ],
)
async def test_misclassified_experience_cannot_bypass_verification(text, kind, status):
    report = await verify_claims(text, [], FakeLLM([judgment(text, kind, status)]))
    assert report.cleaned_draft == ""


@pytest.mark.parametrize(
    "text,kind", [("Hello!", "nonfactual"), ("I will analyze the data.", "intent")]
)
async def test_greetings_and_future_approach_survive(text, kind):
    report = await verify_claims(text, [], FakeLLM([judgment(text, kind, "supported")]))
    assert report.cleaned_draft == text


async def test_unchecked_sentence_tail_fails_closed():
    report = await verify_claims(
        "Hello and I achieved 100% accuracy.",
        [],
        FakeLLM([judgment("Hello", "nonfactual", "supported")]),
    )
    assert report.cleaned_draft == "" and report.status == "needs_attention"


def test_claim_denominators_and_incomplete_assessment():
    counts = claim_counts(
        {
            "status": "verified",
            "sentences": [
                {
                    "claims": [
                        {"text": "a", "kind": "experience", "status": "supported"},
                        {"text": "b", "kind": "experience", "status": "unsupported"},
                        {
                            "text": "c",
                            "kind": "experience",
                            "status": "partly_supported",
                        },
                        {"text": "Hi", "kind": "nonfactual", "status": "supported"},
                    ]
                }
            ],
        }
    )
    assert counts == {
        "experience": 3,
        "unsupported": 1,
        "partly_supported": 1,
        "supported_texts": ["a"],
    }
    with pytest.raises(ValueError):
        claim_counts({"status": "needs_attention"})


def test_kappa_and_single_score_validation():
    assert agreement([1, 2, 3, 4, 5], [1, 2, 3, 4, 5])["cohens_kappa"] == 1
    assert agreement([1, 1], [1, 1])["cohens_kappa"] is None
    assert agreement([1, 2], [2, 1])["cohens_kappa"] == -1
    with pytest.raises(ValueError):
        agreement([0], [1])
    with pytest.raises(ValueError):
        agreement([1], [1, 2])


def test_unfilled_calibration_rejected(tmp_path):
    (tmp_path / "rag_calibration_key.json").write_text("[]")
    (tmp_path / "rag_human_review.csv").write_text("review_id,human_score\n")
    with pytest.raises(ValueError, match="30"):
        calibrate(tmp_path)


def test_failed_runs_have_no_fabricated_metrics():
    result = summarize(
        [
            {
                "id": "one",
                "persona": "ml",
                "category": "ML",
                "variant": "v0",
                "error": {"code": "offline"},
                "assessment_error": None,
                "outcome_error": None,
                "usage": {},
                "timings": {},
            }
        ]
    )["all"]["v0"]
    assert result["failures"] == 1
    assert result["p95_proposal_seconds"] is None
    assert result["unsupported_claims_per_proposal"] is None
    assert result["reply_rate"] is None
    assert result["after_unsupported_rate"] is None


async def test_isolated_mcp_outcomes_repeat_and_derive_actual_skills():
    case = json.loads((ROOT / "evals/datasets/rag_jobs.json").read_text())["cases"][0]
    # Explicit fixture preferences exercise the skill gate; published runs retain original preferences.
    case["client"]["hire_rate"] = 0.9
    case["client"]["hidden_preferences"]["must_have_skills"] = ["python"]
    case["job"]["skills"] = ["python"]
    first = await simulate_outcome(case, "I will use Python to solve this task.", 42)
    second = await simulate_outcome(case, "I will use Python to solve this task.", 42)
    assert first == second and first["submitted"]
    absent = await simulate_outcome(case, "I will solve the task.", 42)
    assert absent["status"] == "no_reply"
    assert not (await simulate_outcome(case, "", 42))["submitted"]


async def test_independent_assessment_does_not_apply_removal_policy():
    from evals.runners.rag_workflow import assess_draft

    text = "What is your deadline?"
    report = await assess_draft(
        text, [], FakeLLM([judgment(text, "nonfactual", "supported")])
    )
    assert report["status"] == "verified"
    assert claim_counts(report)["experience"] == 0


async def test_independent_assessment_rejects_invented_and_inconsistent_claims():
    from evals.runners.rag_workflow import assess_draft

    text = "I achieved perfect accuracy."
    report = await assess_draft(
        text, [], FakeLLM([judgment(text, "nonfactual", "unsupported")])
    )
    assert report["status"] == "needs_attention"
    report = await assess_draft(
        text, [], FakeLLM([judgment("Invented text", "experience", "supported")])
    )
    assert report["status"] == "needs_attention"


def test_review_pack_imports_one_score_and_detects_text_tampering(tmp_path):
    import csv

    from evals.runners.rag_calibration import review_pack
    from rag.config import VARIANTS

    cases, rows = [], []
    for variant in VARIANTS:
        for i in range(6):
            case_id = f"{variant}-{i}"
            cases.append(
                {"id": case_id, "job": {"title": "Task", "description": "Build it"}}
            )
            rows.append(
                {
                    "id": case_id,
                    "variant": variant,
                    "persona": f"test-{i % 3}",
                    "category": "test",
                    "judge_score_uncalibrated": i % 5 + 1,
                    "cleaned_draft": "Test proposal.",
                    "retrieval": {"hits": []},
                    "fingerprint": "test-only",
                }
            )
    (tmp_path / "rag_workflow_observations.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n"
    )
    (tmp_path / "rag_jobs.json").write_text(json.dumps({"cases": cases}))
    # The report's summary has the normal aggregate shape; these are test-only fixtures.
    summary = {
        "complete": False,
        "results": {
            "all": {
                v: {
                    "assessed_proposals": 0,
                    "before_unsupported_claims": 0,
                    "before_experience_claims": 0,
                    "after_unsupported_claims": 0,
                    "after_experience_claims": 0,
                    "before_unsupported_rate": None,
                    "after_unsupported_rate": None,
                    "supported_retention_rate": None,
                    "failures": 0,
                    "submitted": 0,
                }
                for v in VARIANTS
            }
        },
    }
    (tmp_path / "rag_workflow.json").write_text(json.dumps(summary))
    review_pack(tmp_path)
    key = {
        r["review_id"]: r
        for r in json.loads((tmp_path / "rag_calibration_key.json").read_text())
    }
    path = tmp_path / "rag_human_review.csv"
    with path.open(newline="") as handle:
        labels = list(csv.DictReader(handle))
    assert len(labels) == 30
    assert not {"variant", "judge_score"} & labels[0].keys()
    fields = list(labels[0])
    for row in labels:
        row["human_score"] = str(key[row["review_id"]]["judge_score"])

    def save():
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(labels)

    save()
    assert calibrate(tmp_path)["cohens_kappa"] == 1
    # Re-running pack preparation must preserve the human's entered scores.
    before = path.read_bytes()
    review_pack(tmp_path)
    assert path.read_bytes() == before
    labels[0]["proposal"] = "Tampered."
    save()
    with pytest.raises(ValueError, match="text was edited"):
        calibrate(tmp_path)


async def test_ordinary_question_survives_but_embedded_self_claim_does_not():
    text = "What is your deadline?"
    report = await verify_claims(
        text, [], FakeLLM([judgment(text, "nonfactual", "supported")])
    )
    assert report.cleaned_draft == text
    text = "How can my 100 successful projects help?"
    report = await verify_claims(
        text, [], FakeLLM([judgment(text, "nonfactual", "supported")])
    )
    assert report.cleaned_draft == ""


def test_resume_rejects_duplicates_unexpected_keys_and_changed_fingerprints():
    from evals.runners.rag_workflow import validate_resume

    row = {"id": "one", "variant": "v0", "fingerprint": "same"}
    expected = {("one", "v0")}
    validate_resume([row], expected, "same")
    with pytest.raises(ValueError, match="Duplicate"):
        validate_resume([row, row], expected, "same")
    with pytest.raises(ValueError, match="unexpected"):
        validate_resume([{**row, "id": "other"}], expected, "same")
    with pytest.raises(ValueError, match="Cannot resume"):
        validate_resume([row], expected, "changed")


async def test_supported_nonfactual_label_cannot_hide_experience_from_metrics():
    from evals.runners.rag_workflow import assess_draft

    text = "I achieved perfect accuracy."
    report = await assess_draft(
        text, [], FakeLLM([judgment(text, "nonfactual", "supported")])
    )
    assert report["status"] == "needs_attention"
    assert report["raw_judgments"]
    assert report["message"] == "Inconsistent factual classification"


def test_review_pack_fills_sparse_persona_cells_without_rerunning_models(tmp_path):
    import csv

    from evals.runners.rag_calibration import review_pack
    from rag.config import VARIANTS

    cases, rows = [], []
    for variant in VARIANTS:
        for persona, count in (("ml", 1), ("web", 3), ("data", 3)):
            for i in range(count):
                case_id = f"{variant}-{persona}-{i}"
                cases.append(
                    {"id": case_id, "job": {"title": "Task", "description": "Build"}}
                )
                rows.append(
                    {
                        "id": case_id,
                        "variant": variant,
                        "persona": persona,
                        "judge_score_uncalibrated": 3,
                        "cleaned_draft": "Draft.",
                        "retrieval": {"hits": []},
                        "fingerprint": "test",
                    }
                )
    (tmp_path / "rag_workflow_observations.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n"
    )
    (tmp_path / "rag_jobs.json").write_text(json.dumps({"cases": cases}))
    result = review_pack(tmp_path)
    assert result["status"] == "created"
    key = json.loads((tmp_path / "rag_calibration_key.json").read_text())
    assert len(key) == 30
    assert all(sum(r["variant"] == v for r in key) == 6 for v in VARIANTS)
    with (tmp_path / "rag_human_review.csv").open(newline="") as handle:
        assert all(r["human_score"] == "" for r in csv.DictReader(handle))


def test_review_pack_reports_shortage_instead_of_silently_skipping(tmp_path):
    from evals.runners.rag_calibration import review_pack

    (tmp_path / "rag_workflow_observations.jsonl").write_text(
        json.dumps(
            {
                "id": "one",
                "variant": "v0",
                "persona": "ml",
                "judge_score_uncalibrated": 3,
            }
        )
        + "\n"
    )
    result = review_pack(tmp_path)
    assert result["status"] == "pending" and result["deficits"]
    assert not (tmp_path / "rag_human_review.csv").exists()
