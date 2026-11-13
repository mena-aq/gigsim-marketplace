"""Offline R&D B hypothesis: does reranking improve hybrid retrieval nDCG@10?"""

import argparse
import hashlib
from pathlib import Path

from evals.runners.rag_study import (
    StudyError,
    bootstrap,
    breakdowns,
    display_path,
    file_hash,
    load_dataset,
    load_pairs,
    paired_rows,
    write_reports,
)
from rag.config import ROOT

HYPOTHESIS = "Adding cross-encoder reranking to hybrid retrieval improves mean nDCG@10."


def analyze(
    run: Path, dataset_path: Path, samples: int = 10000, seed: int = 42
) -> tuple[dict, list[dict], dict]:
    dataset = load_dataset(dataset_path)
    rows, fingerprint = load_pairs(run, dataset)
    rows = [{**row, "configuration": row["variant"]} for row in rows]
    pairs = paired_rows(rows, dataset["queries"], "v3", "v2")
    result = bootstrap(pairs, samples, seed)
    by_group = {}
    for key in ("persona", "query_type"):
        for value in sorted({pair[key] for pair in pairs}):
            by_group[key + ":" + value] = bootstrap(
                [pair for pair in pairs if pair[key] == value], samples, seed
            )
    finding = {
        "observed_improvement": "The interval is above zero: this development set favors reranking on nDCG@10.",
        "observed_decrease": "The interval is below zero: reranking reduced nDCG@10 on this development set.",
        "no_observed_difference": "The paired scores are equal: this set shows no reranking benefit.",
        "inconclusive": "The interval includes zero: this set does not establish a clear direction.",
    }[result["outcome"]]
    summary = {
        "hypothesis": HYPOTHESIS,
        "primary_metric": "mean paired nDCG@10 difference, V3 minus V2",
        "source_run": display_path(run),
        "source_sha256": file_hash(run),
        "source_fingerprint": fingerprint,
        "analysis_code_sha256": hashlib.sha256(
            Path(__file__).read_bytes()
            + (ROOT / "evals/runners/rag_study.py").read_bytes()
            + (ROOT / "evals/runners/rag_eval.py").read_bytes()
        ).hexdigest(),
        "source_environment": display_path(run.with_suffix(".environment.json"))
        if run.with_suffix(".environment.json").is_file()
        else None,
        "dataset_sha256": file_hash(dataset_path),
        "labels_reviewed": dataset.get("reviewed_by_user", False),
        "primary_result": result,
        "finding": finding,
        "paired_breakdowns": by_group,
        "breakdowns": breakdowns(rows, dataset["queries"], ("v2", "v3")),
        "interpretation": "Exploratory paired comparison; provisional labels and small samples do not establish production or reply-rate superiority.",
        "label_policy": "Re-score saved rankings with the supplied labels; preserve query text for existing IDs. Historical runs do not store query text, so the original query text cannot be independently checked offline.",
        "selection": "The user chooses the production variant; no configuration is modified",
    }
    evidence = [
        {
            **pair,
            "v2": next(
                row
                for row in rows
                if row["id"] == pair["id"] and row["configuration"] == "v2"
            ),
            "v3": next(
                row
                for row in rows
                if row["id"] == pair["id"] and row["configuration"] == "v3"
            ),
        }
        for pair in pairs
    ]
    return summary, evidence, dataset


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument(
        "--dataset", type=Path, default=ROOT / "evals/datasets/rag_dev.json"
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT / "evals/results")
    args = parser.parse_args(argv)
    try:
        summary, rows, dataset = analyze(args.run, args.dataset)
    except (StudyError, OSError, ValueError) as exc:
        parser.error(str(exc))
    result = summary["primary_result"]
    text = (
        f"# R&D B: reranking hypothesis\n\n{HYPOTHESIS}\n\n"
        f"Exploratory results; labels reviewed: {summary['labels_reviewed']}.\n\n"
        f"Primary comparison: V3 minus V2 on {result['pairs']} positive queries.\n"
        f"Mean paired difference: {result['mean_delta']:.4f}; "
        f"95% bootstrap interval: {result['ci95']}.\n"
        f"Outcome: {result['outcome']}. {summary['finding']}\n\n"
        "No-evidence queries are excluded from ranking metrics.\n\n"
        "Latency is copied from the saved run; this script makes no model or database calls.\n"
        "Rankings are re-scored against the supplied labels. Keep the original query text for each ID.\n"
        "Per-persona/type deltas, failures, and per-query evidence are in the JSON files."
    )
    write_reports(args.output_dir, "rag_rd_b", summary, rows, dataset, text)
    print(
        f"Wrote {display_path(args.output_dir / 'rag_rd_b.md')}; outcome: {result['outcome']}"
    )


if __name__ == "__main__":
    main()
