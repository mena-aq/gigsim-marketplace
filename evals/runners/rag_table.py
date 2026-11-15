"""Offline regeneration of the single Part B CSV, report, and README table."""

import argparse
import csv
import json
import os
import shutil
from pathlib import Path
from statistics import mean

from evals.runners.rag_calibration import calibrate, digest, review_pack
from evals.runners.rag_diagnostics import failure_diagnostics
from rag.config import ROOT, VARIANTS

RESULTS = ROOT / "evals/results"
FIELDS = [
    "Variant",
    "Evidence Recall@5",
    "nDCG@10",
    "Unsupported claims per proposal",
    "Judge score",
    "GigSim reply rate",
    "p95 latency (s)",
    "Cost per proposal (USD)",
]


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def save(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def import_legacy(folder: Path = RESULTS) -> None:
    """Copy completed measurements/labels without rerunning or editing originals."""
    marker = folder / "rag_import.json"
    if marker.exists():
        return
    old = folder / "proposal"
    mapping = {
        "retrieval_snapshot.json": "rag_retrieval.json",
        "proposal_summary.json": "rag_workflow.json",
        "proposal_observations.jsonl": "rag_workflow_observations.jsonl",
        "proposal_dataset.json": "rag_jobs.json",
        "proposal_environment.json": "rag_workflow.environment.json",
        "human_review.csv": "rag_human_review.csv",
        "human_review.md": "rag_human_review.md",
        "calibration_key.json": "rag_calibration_key.json",
        "judge_calibration.json": "rag_judge_calibration.json",
    }
    required = list(mapping)[:4]
    if not all((old / name).exists() for name in required):
        raise ValueError(
            "No completed legacy measurements to import; run make rag-eval"
        )
    sources = {}
    for source, target in mapping.items():
        src, dst = old / source, folder / target
        if not src.exists():
            continue
        if dst.exists() and digest(dst) != digest(src):
            raise ValueError(f"Refusing to overwrite existing {dst.name}")
        shutil.copyfile(src, dst)
        if source == "human_review.md":
            dst.write_text(
                dst.read_text()
                .replace("human_review.csv", "rag_human_review.csv")
                .replace("calibration_key.json", "rag_calibration_key.json")
            )
        sources[target] = {"original": str(src.resolve()), "sha256": digest(src)}
    retrieval = read(folder / "rag_retrieval.json")
    observations = Path(retrieval["observations"])
    if not observations.is_absolute():
        observations = ROOT / observations
    if not observations.exists():
        raise ValueError("Historical retrieval observations are missing")
    dst = folder / "rag_retrieval_observations.jsonl"
    if dst.exists() and digest(dst) != digest(observations):
        raise ValueError("Refusing to overwrite retrieval observations")
    shutil.copyfile(observations, dst)
    sources[dst.name] = {
        "original": str(observations.resolve()),
        "sha256": digest(observations),
    }
    save(
        marker,
        {
            "mode": "imported_existing_measurements",
            "sources": sources,
            "note": "Original fingerprints and human labels preserved; no inference rerun",
        },
    )


def active_folder() -> Path:
    """Resolve the last published unified run; import completed history once."""
    current = RESULTS / "rag_comparison.json"
    if current.exists() and read(current).get("schema_version") == 2:
        folder = Path(read(current)["artifact_directory"])
        if not folder.is_dir():
            raise ValueError("Published RAG artifact directory is missing")
        return folder
    import_legacy()
    return RESULTS


def build_summary(folder: Path) -> dict:
    """Combine benchmark stages and calibration with exact source provenance."""
    retrieval = read(folder / "rag_retrieval.json")
    workflow = read(folder / "rag_workflow.json")
    rows = [
        json.loads(line)
        for line in (folder / "rag_workflow_observations.jsonl")
        .read_text()
        .splitlines()
    ]
    calibration_path = folder / "rag_judge_calibration.json"
    calibration = read(calibration_path) if calibration_path.exists() else {}
    labels = folder / "rag_human_review.csv"
    reviewed = (
        calibration.get("items") == 30
        and labels.exists()
        and calibration.get("observations_sha256")
        == digest(folder / "rag_workflow_observations.jsonl")
        and calibration.get("human_review_sha256") == digest(labels)
    )
    cases = {c["id"]: c for c in read(folder / "rag_jobs.json")["cases"]}
    for group, variants in workflow["results"].items():
        for variant, arm in variants.items():
            matching = [r for r in rows if r["variant"] == variant]
            if group != "all":
                field, value = group.split(":", 1)
                matching = [r for r in matching if r[field] == value]
            arm.update(failure_diagnostics(matching, cases))
            scores = [
                r["judge_score_uncalibrated"]
                for r in matching
                if r.get("judge_score_uncalibrated") is not None
            ]
            arm["judge_score"] = mean(scores) if reviewed and scores else None
            arm["judge_status"] = (
                calibration["status"] if reviewed else "pending_human_calibration"
            )
            arm["judge_scored_proposals"] = len(scores)
    ablation_path = folder / "rag_ablation.json"
    ablation = read(ablation_path) if ablation_path.exists() else None
    all_ret, all_work = retrieval["retrieval"]["all"], workflow["results"]["all"]
    table = []
    for variant in VARIANTS:
        ret, work = all_ret.get(variant, {}), all_work.get(variant, {})
        table.append(
            dict(
                zip(
                    FIELDS,
                    [
                        variant,
                        ret.get("recall_at_5"),
                        ret.get("ndcg_at_10"),
                        work.get("unsupported_claims_per_proposal"),
                        work.get("judge_score"),
                        work.get("reply_rate"),
                        work.get("p95_proposal_seconds"),
                        work.get("total_cost_per_proposal_usd"),
                    ],
                    strict=True,
                )
            )
        )
    source_names = [
        "rag_retrieval.json",
        "rag_retrieval_observations.jsonl",
        "rag_workflow.json",
        "rag_workflow_observations.jsonl",
        "rag_jobs.json",
        "rag_judge_calibration.json",
        "rag_human_review.csv",
        "rag_ablation.json",
        "rag_environment.json",
        "rag_preflight.json",
        "rag_import.json",
    ]
    sources = {
        name: {"path": str((folder / name).resolve()), "sha256": digest(folder / name)}
        for name in source_names
        if (folder / name).exists()
    }
    return {
        **retrieval,
        "schema_version": 2,
        "artifact_directory": str(folder.resolve()),
        "complete": bool(
            retrieval.get("complete", True) and workflow["complete"] and ablation
        ),
        "full_benchmark": (
            set(all_ret) == set(VARIANTS)
            and set(all_work) == set(VARIANTS)
            and all(v["queries"] == 30 for v in all_ret.values())
            and all(v["attempted"] == 30 for v in all_work.values())
        ),
        "claim_regressions": retrieval.get("verification", {}),
        "verification": {
            group: {
                variant: {
                    key: value
                    for key, value in arm.items()
                    if key
                    in {
                        "assessed_proposals",
                        "before_experience_claims",
                        "after_experience_claims",
                        "before_unsupported_claims",
                        "after_unsupported_claims",
                        "before_unsupported_rate",
                        "after_unsupported_rate",
                        "unsupported_claims_per_proposal",
                        "supported_retention_rate",
                        "partly_supported_claims_after",
                        "empty_drafts",
                        "needs_attention",
                    }
                }
                for variant, arm in variants.items()
            }
            for group, variants in workflow["results"].items()
        },
        "workflow": workflow["results"],
        "calibration": calibration,
        "calibration_current": reviewed,
        "ablation": ablation,
        "table": table,
        "sources": sources,
        "workflow_profile": "rag_benchmark",
        "fixture_note": "One RAG benchmark with labelled retrieval queries, controlled claim regressions, and fixed GigSim jobs; historical fixture populations differ.",
    }


def fmt(value) -> str:
    return "not measured" if value is None else f"{value:.3f}"


def render(summary: dict, folder: Path) -> str:
    """Render B5, B3 denominators, and ablation in one engineering report."""
    cal = summary["calibration"]
    lines = [
        "## RAG evaluation — B3, B5 and ablation",
        "",
        f"Run status: {'complete' if summary['complete'] else 'partial'}. Workflow: RAG benchmark.",
        "",
        (
            "One evaluation covers retrieval, drafting, claim verification, quality judging, and simulated replies. "
            "The imported measurements use labelled retrieval queries and a fixed GigSim job set; they are separate fixtures, not paired observations of the same jobs. "
            "p95 covers retrieval → drafting → verification and excludes assessment, judging and simulator waiting. "
            "Paid API spend is zero for local inference; total hardware cost is unmeasured."
        ),
        "",
    ]
    if summary["calibration_current"]:
        lines += [
            (
                f"Judge calibration: {cal['items']} human scores; exact agreement {cal['exact_agreement']:.1%}; Cohen's κ = {fmt(cal['cohens_kappa'])}. "
                "Judge means are published alongside agreement; low agreement makes them provisional."
            ),
            "",
        ]
    else:
        lines += [
            "Judge means await 30 matching human scores. Existing labels are never replaced automatically.",
            "",
        ]
    lines += [
        "| " + " | ".join(FIELDS) + " |",
        "| " + " | ".join(["---"] * len(FIELDS)) + " |",
    ]
    for row in summary["table"]:
        lines.append(
            "| "
            + " | ".join([row["Variant"]] + [fmt(row[f]) for f in FIELDS[1:]])
            + " |"
        )
    lines += [
        "",
        "### Claim verification and outcome denominators",
        "",
        "| Variant | Assessed drafts | Unsupported before | Unsupported after | Supported retention | Failures | Submitted | Replies |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for variant, work in summary["workflow"]["all"].items():
        lines.append(
            "| "
            + " | ".join(
                [
                    variant,
                    str(work["assessed_proposals"]),
                    f"{work['before_unsupported_claims']}/{work['before_experience_claims']} ({fmt(work['before_unsupported_rate'])})",
                    f"{work['after_unsupported_claims']}/{work['after_experience_claims']} ({fmt(work['after_unsupported_rate'])})",
                    fmt(work["supported_retention_rate"]),
                    str(work["failures"]),
                    str(work["submitted"]),
                    str(work.get("replies", 0)),
                ]
            )
            + " |"
        )
    lines += [
        "",
        (
            "Unsupported rates use independently assessed atomic experience claims; partly supported claims and incomplete assessments are recorded in JSON. "
            "An empty denominator is undefined. A zero unsupported count with few assessed claims does not establish zero hallucination risk. "
            "Supported retention uses exact claim text and may be affected by segmentation."
        ),
        "",
        (
            "Reply rate = replied/interview/hired outcomes divided by submitted proposals with completed outcomes. Empty drafts and failed submissions are excluded from that denominator; "
            "JSON also records reply yield per attempted job, empty drafts, and outcome failures. GigSim runs in fresh in-memory fixtures through real MCP tools, "
            "with the same job/client/random seed for each variant and skill mentions derived from the cleaned text. It checks skill mentions, generic openings and randomness, not semantic proposal quality."
        ),
        "",
    ]
    lines += [
        "### Failure and reply-gate breakdown",
        "",
        "| Variant | Embedding failures | Decomposition failures | Other model failures | Verifier errors | Assessment failures | Skill rejects | Eligible no-reply |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for variant, work in summary["workflow"]["all"].items():
        errors = work.get("failure_categories", {})
        lines.append(
            "| "
            + " | ".join(
                map(
                    str,
                    [
                        variant,
                        errors.get("embedding", 0),
                        errors.get("decomposition", 0),
                        errors.get("structured_model", 0),
                        work.get("verification_failure_count", 0),
                        work.get("assessment_failures", 0),
                        work.get("reply_gate_counts", {}).get("skill_mismatch", 0),
                        work.get("reply_reason_counts", {}).get("eligible_no_reply", 0),
                    ],
                )
            )
            + " |"
        )
    lines += [
        "",
        (
            "Verifier/assessment errors may overlap a completed draft and are not added to job failures. "
            "Historical reply gates are reconstructed from the saved job/client/draft; this does not change the recorded outcome."
        ),
        "",
    ]
    ablation = summary["ablation"]
    if ablation:
        lines += [
            "### Component ablation",
            "",
            (
                "Full V3 = dense + BM25 + reranking. Positive full-minus-ablated deltas favor the retained component. "
                "This retrieval-only component test runs within rag-eval; it does not generate extra proposals."
            ),
            "",
            "| Component removed | Paired nDCG@10 delta | 95% bootstrap interval |",
            "| --- | --- | --- |",
        ]
        for component, effect in ablation["component_effects"].items():
            lines.append(
                f"| {component} | {effect['mean_delta']:.4f} | {effect['ci95']} |"
            )
    lines += [
        "",
        (
            "Per-persona/category results, MRR, p50, tokens, partial support, hire rate and failures are in the JSON. "
            "The production agent graph and blind pairwise classmate panel remain future work. No shipped variant has been selected."
        ),
        "",
        "Sources:",
        "",
    ]
    for name, source in summary["sources"].items():
        lines.append(f"- [{name}]({os.path.relpath(source['path'], folder)})")
    rd = RESULTS / "rag_rd_b.md"
    lines += [
        "",
        f"The completed [V2–V3 R&D hypothesis study]({os.path.relpath(rd, folder)}) remains separate and is not rerun by rag-eval.",
        "",
    ]
    return "\n".join(lines)


def render_readme(summary: dict, folder: Path) -> str:
    """Render the compact published RAG summary used by the root README."""
    lines = [
        "## Evaluation",
        "",
        (
            "Run the complete benchmark with `make rag-eval`. Use `make rag-table` "
            "to regenerate committed summaries offline and `make rag-calibrate` "
            "to import human scores."
        ),
        "",
        (
            "The committed comparison below is the published `rag-eval` summary. "
            "Judge scores are provisional and hardware cost is not measured."
        ),
        "",
        "| " + " | ".join(FIELDS) + " |",
        "| " + " | ".join(["---"] * len(FIELDS)) + " |",
    ]
    for row in summary["table"]:
        lines.append(
            "| "
            + " | ".join([row["Variant"]] + [fmt(row[f]) for f in FIELDS[1:]])
            + " |"
        )
    lines += [
        "",
        (
            "Regenerate the committed table offline with `make rag-table`; this "
            "does not call models. Run `make rag-calibrate` to import human scores."
        ),
        "",
        (
            "The full report, additional breakdowns, raw measurements, calibration "
            "labels, and artifact provenance are committed in "
            "[evals/results](evals/results/README.md), especially the "
            "[full RAG report](evals/results/rag_comparison.md), "
            "[CSV](evals/results/rag_comparison.csv), and "
            "[JSON summary](evals/results/rag_comparison.json)."
        ),
        "",
        (
            "The separate V2–V3 R&D hypothesis study is in "
            "[evals/results/rag_rd_b.md](evals/results/rag_rd_b.md)."
        ),
    ]
    return "\n".join(lines)


def write_report(
    folder: Path, *, publish: bool = False, update_readme: bool = False
) -> dict:
    """Regenerate CSV/Markdown/JSON offline, optionally publishing the active run."""
    folder = folder.resolve()
    summary = build_summary(folder)
    text = render(summary, folder)
    save(folder / "rag_comparison.json", summary)
    with (folder / "rag_comparison.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(summary["table"])
    (folder / "rag_comparison.md").write_text(text)
    if publish or update_readme:
        if not summary["complete"] or not summary["full_benchmark"]:
            raise ValueError(
                "Publishing requires all five variants, 30 queries, 30 jobs, and completed ablation"
            )
        if folder != RESULTS.resolve():
            save(RESULTS / "rag_comparison.json", summary)
            shutil.copyfile(
                folder / "rag_comparison.csv", RESULTS / "rag_comparison.csv"
            )
            (RESULTS / "rag_comparison.md").write_text(render(summary, RESULTS))
        if update_readme:
            path = ROOT / "README.md"
            original = path.read_text()
            begin, end = "<!-- B3_B5_START -->", "<!-- B3_B5_END -->"
            block = begin + "\n" + render_readme(summary, ROOT) + "\n" + end
            if begin in original and end in original:
                original = (
                    original[: original.index(begin)]
                    + block
                    + original[original.index(end) + len(end) :]
                )
            else:
                original = original.rstrip() + "\n\n" + block + "\n"
            path.write_text(original)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--update-readme", action="store_true")
    args = parser.parse_args()
    try:
        folder = args.output_dir.resolve() if args.output_dir else active_folder()
        print(json.dumps({"review_pack": review_pack(folder)}))
        if args.calibrate:
            result = calibrate(folder)
            print(
                json.dumps(
                    {
                        k: result[k]
                        for k in ("status", "exact_agreement", "cohens_kappa")
                    }
                )
            )
        write_report(folder, publish=True, update_readme=args.update_readme)
        print(f"RAG results CSV: {RESULTS / 'rag_comparison.csv'}")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"RAG table stopped: {exc}\n")


if __name__ == "__main__":
    main()
