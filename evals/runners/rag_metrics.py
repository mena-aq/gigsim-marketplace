"""Shared RAG benchmark metrics and model/index fingerprints."""

import hashlib
import json
import math
from statistics import mean

from rag.config import ROOT, VARIANTS


def metrics(ids: list[str], qrels: dict) -> dict:
    if not qrels:
        return {
            "recall_at_5": None,
            "mrr": None,
            "ndcg_at_10": None,
            "correct_abstention": not ids,
        }
    recall = len(set(ids[:5]) & set(qrels)) / len(qrels)
    reciprocal = next((1 / (i + 1) for i, key in enumerate(ids) if key in qrels), 0)
    gain = sum(
        (2 ** qrels.get(key, 0) - 1) / math.log2(i + 2)
        for i, key in enumerate(ids[:10])
    )
    ideal = sum(
        (2**grade - 1) / math.log2(i + 2)
        for i, grade in enumerate(sorted(qrels.values(), reverse=True)[:10])
    )
    return {
        "recall_at_5": recall,
        "mrr": reciprocal,
        "ndcg_at_10": gain / ideal if ideal else 0,
        "correct_abstention": None,
    }


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def aggregate(rows: list[dict]) -> dict:
    output = {}
    groups = {"all": rows}
    for persona in sorted({row["persona"] for row in rows}):
        groups[persona] = [row for row in rows if row["persona"] == persona]
    for kind in sorted({row["query_type"] for row in rows}):
        groups["type:" + kind] = [row for row in rows if row["query_type"] == kind]
    for name, group in groups.items():
        output[name] = {}
        for variant in VARIANTS:
            selected = [row for row in group if row["variant"] == variant]
            if not selected:
                continue
            result = {
                "queries": len(selected),
                "failures": sum(row["error"] is not None for row in selected),
                "p50_seconds": percentile([row["seconds"] for row in selected], 0.5),
                "p95_seconds": percentile([row["seconds"] for row in selected], 0.95),
                "prompt_tokens": sum(
                    call["prompt_tokens"]
                    for row in selected
                    for call in row["llm_usage"]
                ),
                "completion_tokens": sum(
                    call["completion_tokens"]
                    for row in selected
                    for call in row["llm_usage"]
                ),
            }
            for metric in ("recall_at_5", "mrr", "ndcg_at_10", "correct_abstention"):
                values = [
                    row["metrics"][metric]
                    for row in selected
                    if row["metrics"][metric] is not None
                ]
                result[metric] = mean(values) if values else None
            output[name][variant] = result
    return output


def code_fingerprint(config, manifests, dataset, claimset) -> str:
    files = sorted((ROOT / "rag").rglob("*.py")) + sorted(
        (ROOT / "agent/prompts").glob("rag_*.md")
    )
    content = b"".join(path.read_bytes() for path in files)
    body = {
        "config": config.model_dump(mode="json"),
        "indexes": {
            key: hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
            for key, value in manifests.items()
        },
        "dataset": dataset,
        "claimset": claimset,
    }
    return hashlib.sha256(
        content + json.dumps(body, sort_keys=True).encode()
    ).hexdigest()
