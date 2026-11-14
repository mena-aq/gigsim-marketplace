"""Shared validation, paired statistics, and report writing for small RAG studies."""

import csv
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

import numpy as np

from evals.runners.rag_metrics import metrics, percentile
from rag.config import ROOT


class StudyError(ValueError):
    """Invalid or mismatched study inputs; do not silently omit measurements."""


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def display_path(path: Path) -> str:
    resolved = path.resolve()
    return (
        str(resolved.relative_to(ROOT))
        if resolved.is_relative_to(ROOT)
        else str(resolved)
    )


def load_dataset(path: Path) -> dict:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise StudyError("Dataset must be an object")
    queries = data.get("queries")
    if not isinstance(queries, list) or not queries:
        raise StudyError("Dataset must contain a nonempty queries list")
    seen = set()
    for query in queries:
        if not isinstance(query, dict):
            raise StudyError("Every query must be an object")
        for key in ("id", "persona", "type", "query"):
            if not isinstance(query.get(key), str) or not query[key].strip():
                raise StudyError(f"Every query needs a nonempty {key}")
        if query["id"] in seen:
            raise StudyError("Duplicate query IDs in dataset")
        seen.add(query["id"])
        qrels = query.get("qrels")
        if not isinstance(qrels, dict) or any(
            not isinstance(key, str)
            or not key
            or type(grade) is not int
            or not 0 <= grade <= 3
            for key, grade in qrels.items()
        ):
            raise StudyError(
                "qrels must map source IDs to integer relevance grades 0–3"
            )
        # Zero-grade judgments are nonrelevant, not Recall denominator entries.
        query["qrels"] = {key: grade for key, grade in qrels.items() if grade > 0}
    if not any(query["qrels"] for query in queries):
        raise StudyError("At least one positive query is required for the hypothesis")
    return data


def rescore(row: dict, query: dict) -> dict:
    ids = [] if row["error"] is not None else row["returned_ids"]
    result = metrics(ids, query["qrels"])
    if row["error"] is not None and not query["qrels"]:
        result["correct_abstention"] = False
    return result


def load_pairs(path: Path, dataset: dict) -> tuple[list[dict], str]:
    queries = {query["id"]: query for query in dataset["queries"]}
    selected = {}
    seen = set()
    fingerprints = set()
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise StudyError(f"Invalid JSON on observation line {number}") from exc
        if not isinstance(row, dict):
            raise StudyError("Every observation must be an object")
        if row.get("kind") != "retrieval":
            continue
        fingerprint = row.get("fingerprint")
        if not isinstance(fingerprint, str) or not fingerprint:
            raise StudyError("Retrieval observations need a source fingerprint")
        fingerprints.add(fingerprint)
        key = (row.get("id"), row.get("variant"))
        if key in seen:
            raise StudyError(f"Duplicate observation: {key}")
        seen.add(key)
        if row.get("variant") not in ("v2", "v3"):
            continue
        if row.get("id") not in queries:
            raise StudyError("Run contains query IDs absent from the supplied dataset")
        query = queries[row["id"]]
        if (
            row.get("persona") != query["persona"]
            or row.get("query_type") != query["type"]
        ):
            raise StudyError("Run persona/query type does not match the dataset")
        seconds = row.get("seconds")
        if (
            type(seconds) not in (int, float)
            or not math.isfinite(seconds)
            or seconds < 0
        ):
            raise StudyError("Latency must be a finite, nonnegative number")
        ids = row.get("returned_ids")
        if (
            not isinstance(ids, list)
            or any(not isinstance(key, str) for key in ids)
            or len(ids) != len(set(ids))
        ):
            raise StudyError("Rankings must contain unique string item IDs")
        if (
            "error" not in row
            or row["error"] is not None
            and not isinstance(row["error"], dict)
        ):
            raise StudyError("Observation error must be an object or null")
        selected[key] = {**row, "metrics": rescore(row, query)}
    if len(fingerprints) != 1:
        raise StudyError("Run must contain exactly one retrieval fingerprint")
    expected = {(query_id, variant) for query_id in queries for variant in ("v2", "v3")}
    if set(selected) != expected:
        raise StudyError(
            "Every dataset query must have exactly one V2 and one V3 observation"
        )
    fingerprint = next(iter(fingerprints))
    environment = path.with_suffix(".environment.json")
    if (
        environment.is_file()
        and json.loads(environment.read_text()).get("observation_fingerprint")
        != fingerprint
    ):
        raise StudyError("Environment sidecar belongs to a different run")
    return [
        selected[(query["id"], variant)]
        for query in dataset["queries"]
        for variant in ("v2", "v3")
    ], fingerprint


def summarize(rows: list[dict], queries: list[dict]) -> dict:
    labels = {query["id"]: query for query in queries}
    scores = [rescore(row, labels[row["id"]]) for row in rows]
    result = {
        "queries": len(rows),
        "positive_queries": sum(bool(labels[row["id"]]["qrels"]) for row in rows),
        "failures": sum(row["error"] is not None for row in rows),
        "p50_seconds": percentile([row["seconds"] for row in rows], 0.5),
        "p95_seconds": percentile([row["seconds"] for row in rows], 0.95),
    }
    for key in ("recall_at_5", "mrr", "ndcg_at_10", "correct_abstention"):
        values = [score[key] for score in scores if score[key] is not None]
        result[key] = mean(values) if values else None
    return result


def paired_rows(
    rows: list[dict], queries: list[dict], left: str, right: str
) -> list[dict]:
    indexed = {(row["id"], row["configuration"]): row for row in rows}
    result = []
    for query in queries:
        a, b = indexed[(query["id"], left)], indexed[(query["id"], right)]
        sa, sb = rescore(a, query), rescore(b, query)
        result.append(
            {
                "id": query["id"],
                "persona": query["persona"],
                "query_type": query["type"],
                "positive": bool(query["qrels"]),
                "left_ndcg_at_10": sa["ndcg_at_10"],
                "right_ndcg_at_10": sb["ndcg_at_10"],
                "delta_ndcg_at_10": sa["ndcg_at_10"] - sb["ndcg_at_10"]
                if query["qrels"]
                else None,
                "left_recall_at_5": sa["recall_at_5"],
                "right_recall_at_5": sb["recall_at_5"],
                "left_error": a["error"],
                "right_error": b["error"],
            }
        )
    return result


def bootstrap(pairs: list[dict], samples: int = 10000, seed: int = 42) -> dict:
    if samples <= 0:
        raise StudyError("Bootstrap sample count must be positive")
    positives = [pair for pair in pairs if pair["positive"]]
    if not positives:
        return {
            "pairs": 0,
            "mean_delta": None,
            "ci95": None,
            "outcome": "no_positive_queries",
        }
    rng = np.random.default_rng(seed)
    totals = np.zeros(samples)
    # Resample paired differences within persona, retaining persona sample sizes.
    for persona in sorted({pair["persona"] for pair in positives}):
        values = np.array(
            [
                pair["delta_ndcg_at_10"]
                for pair in positives
                if pair["persona"] == persona
            ]
        )
        totals += values[rng.integers(0, len(values), size=(samples, len(values)))].sum(
            axis=1
        )
    distribution = totals / len(positives)
    low, high = (float(value) for value in np.quantile(distribution, [0.025, 0.975]))
    deltas = [pair["delta_ndcg_at_10"] for pair in positives]
    outcome = (
        "no_observed_difference"
        if all(abs(value) < 1e-12 for value in deltas)
        else "observed_improvement"
        if low > 1e-12
        else "observed_decrease"
        if high < -1e-12
        else "inconclusive"
    )
    return {
        "pairs": len(positives),
        "mean_delta": mean(deltas),
        "ci95": [low, high],
        "bootstrap_samples": samples,
        "seed": seed,
        "resampling": "paired differences, stratified by persona",
        "wins": sum(value > 1e-12 for value in deltas),
        "ties": sum(abs(value) <= 1e-12 for value in deltas),
        "losses": sum(value < -1e-12 for value in deltas),
        "outcome": outcome,
    }


def breakdowns(
    rows: list[dict], queries: list[dict], configurations: tuple[str, ...]
) -> dict:
    groups = {"all": queries}
    for key in ("persona", "type"):
        for value in sorted({query[key] for query in queries}):
            groups[key + ":" + value] = [
                query for query in queries if query[key] == value
            ]
    return {
        name: {
            setting: summarize(
                [
                    row
                    for row in rows
                    if row["configuration"] == setting
                    and row["id"] in {query["id"] for query in selected}
                ],
                selected,
            )
            for setting in configurations
        }
        for name, selected in groups.items()
    }


def comparison_table(aggregates: dict) -> list[dict]:
    return [{"configuration": name, **values} for name, values in aggregates.items()]


def markdown_table(table: list[dict]) -> str:
    fields = (
        "configuration",
        "recall_at_5",
        "mrr",
        "ndcg_at_10",
        "correct_abstention",
        "p50_seconds",
        "p95_seconds",
        "failures",
    )
    lines = [
        "| " + " | ".join(fields) + " |",
        "| " + " | ".join("---" for _ in fields) + " |",
    ]
    for row in table:
        lines.append(
            "| "
            + " | ".join(
                "—"
                if row[key] is None
                else f"{row[key]:.4f}"
                if type(row[key]) is float
                else str(row[key])
                for key in fields
            )
            + " |"
        )
    return "\n".join(lines)


def write_json(path: Path, data) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    )
    temporary.replace(path)


def write_reports(
    folder: Path, prefix: str, summary: dict, rows: list[dict], dataset: dict, text: str
) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    write_json(folder / (prefix + "_dataset.json"), dataset)
    (folder / (prefix + "_queries.jsonl")).write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in rows
        )
    )
    table = comparison_table(summary["breakdowns"]["all"])
    with (folder / (prefix + ".csv")).open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)
    (folder / (prefix + ".md")).write_text(text + "\n\n" + markdown_table(table) + "\n")
    summary["created_at_utc"] = datetime.now(UTC).isoformat()
    summary["evidence"] = {
        "queries": display_path(folder / (prefix + "_queries.jsonl")),
        "dataset": display_path(folder / (prefix + "_dataset.json")),
    }
    write_json(folder / (prefix + ".json"), summary)
