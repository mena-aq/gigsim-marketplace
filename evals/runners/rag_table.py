"""Regenerate the comparison CSV and Markdown from measured results only."""

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    folder = ROOT / "evals/results"
    data = json.loads((folder / "rag_comparison.json").read_text())
    fields = [
        "variant",
        "recall_at_5",
        "mrr",
        "ndcg_at_10",
        "correct_abstention",
        "p50_seconds",
        "p95_seconds",
        "prompt_tokens",
        "completion_tokens",
        "failures",
    ]
    with (folder / "rag_comparison.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for variant, values in data["retrieval"]["all"].items():
            writer.writerow(
                {
                    key: variant if key == "variant" else values.get(key)
                    for key in fields
                }
            )
    lines = [
        "# Provisional retrieval comparison",
        "",
        "Agent-authored labels await user review. Unjudged sources count as nonrelevant.",
        "No winning variant has been selected. Local hardware cost is not estimated.",
        "",
        "| Variant | Recall@5 | MRR | nDCG@10 | Correct abstention | p50 s | p95 s | Failures |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for variant, values in data["retrieval"]["all"].items():
        cells = [variant] + [
            "—"
            if values.get(key) is None
            else str(values[key])
            if key == "failures"
            else f"{values[key]:.3f}"
            for key in (
                "recall_at_5",
                "mrr",
                "ndcg_at_10",
                "correct_abstention",
                "p50_seconds",
                "p95_seconds",
                "failures",
            )
        ]
        lines.append("| " + " | ".join(cells) + " |")
    (folder / "rag_comparison.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
