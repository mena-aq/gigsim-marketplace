"""Real-model RAG comparison; provisional labels, no automatic winner selection."""

import argparse
import asyncio
import hashlib
import json
import math
import platform
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

from sqlalchemy import select

from apps.api.models import MCPCredential, User
from mcp_servers.common.runtime import Runtime
from rag.config import ROOT, VARIANTS, load_config
from rag.ingest.pipeline import read_manifest
from rag.retriever import Pipeline
from rag.types import Chunk, RagFailure
from rag.verify import verify_claims

RESULTS = ROOT / "evals/results"


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


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", type=Path)
    args = parser.parse_args()
    config = load_config()
    dataset = json.loads((ROOT / "evals/datasets/rag_dev.json").read_text())
    claimset = json.loads((ROOT / "evals/datasets/claim_dev.json").read_text())
    runtime = Runtime()
    RESULTS.mkdir(parents=True, exist_ok=True)
    try:
        async with runtime.sessions() as session:
            users = {
                user.persona: user
                for user in (
                    await session.execute(select(User).join(MCPCredential))
                ).scalars()
            }
        manifests = {
            persona: read_manifest(config, user.id) for persona, user in users.items()
        }
        fingerprint = code_fingerprint(config, manifests, dataset, claimset)
        path = args.resume or RESULTS / (
            "rag_" + datetime.now(UTC).strftime("%Y%m%d_%H%M%S") + ".jsonl"
        )
        existing = (
            [json.loads(line) for line in path.read_text().splitlines()]
            if args.resume
            else []
        )
        if any(row["fingerprint"] != fingerprint for row in existing):
            raise SystemExit("Cannot resume: code, models, dataset, or index changed")
        observations = [row for row in existing if row["kind"] == "retrieval"]
        # Recompute derived quality metrics from immutable rankings on resume.
        labels = {query["id"]: query for query in dataset["queries"]}
        for row in observations:
            query = labels[row["id"]]
            row["metrics"] = metrics(row["returned_ids"], query["qrels"])
            if row["error"] and not query["qrels"]:
                row["metrics"]["correct_abstention"] = False
        verified = [row for row in existing if row["kind"] == "verification"]
        completed = {row["id"] + ":" + row.get("variant", "") for row in existing}
        from evals.runners.rag_environment import capture_environment

        await capture_environment(
            config, path.with_suffix(".environment.json"), fingerprint
        )
        with path.open("a") as output:

            def save(row):
                row["fingerprint"] = fingerprint
                output.write(json.dumps(row, ensure_ascii=False) + "\n")
                output.flush()

            for query in dataset["queries"]:
                user = users[query["persona"]]
                source_ids = {
                    record["chunk"]["id"]
                    for record in manifests[user.persona]["records"]
                }
                if not set(query["qrels"]) <= source_ids:
                    raise SystemExit(
                        "A labelled source is missing; review the development dataset"
                    )
                for variant in VARIANTS:
                    if query["id"] + ":" + variant in completed:
                        continue
                    pipeline = Pipeline(
                        config, runtime.settings.mcp_persona_dir, user.id, user.persona
                    )
                    start = time.perf_counter()
                    error = None
                    hits = []
                    diagnostics = {}
                    try:
                        result = await pipeline.retrieve(
                            query["query"], 10, variant=variant
                        )
                        hits = [hit.chunk.id for hit in result.hits]
                        diagnostics = result.diagnostics
                    except RagFailure as exc:
                        error = {"code": exc.code, "message": exc.message}
                    score = metrics(hits, query["qrels"])
                    if error and not query["qrels"]:
                        score["correct_abstention"] = False
                    row = {
                        "kind": "retrieval",
                        "id": query["id"],
                        "persona": user.persona,
                        "query_type": query["type"],
                        "variant": variant,
                        "returned_ids": hits,
                        "metrics": score,
                        "error": error,
                        "diagnostics": diagnostics,
                        "llm_usage": pipeline.llm.usage,
                        "seconds": time.perf_counter() - start,
                    }
                    observations.append(row)
                    save(row)
                    print(
                        query["id"],
                        variant,
                        "ok" if error is None else error["code"],
                        round(row["seconds"], 2),
                        flush=True,
                    )
            for example in claimset["examples"]:
                if example["id"] + ":" in completed:
                    continue
                user = users[example["persona"]]
                pipeline = Pipeline(
                    config, runtime.settings.mcp_persona_dir, user.id, user.persona
                )
                evidence = []
                if example["source_id"]:
                    candidates = [
                        Chunk.model_validate(record["chunk"])
                        for record in manifests[user.persona]["records"]
                        if record["chunk"]["id"] == example["source_id"]
                        and example["evidence_quote"] in record["chunk"]["text"]
                    ]
                    if not candidates:
                        raise SystemExit(
                            "Verification evidence quote missing; review its source/chunking"
                        )
                    evidence = candidates[:1]
                report = await verify_claims(example["draft"], evidence, pipeline.llm)
                kept = bool(report.cleaned_draft.strip())
                row = {
                    "kind": "verification",
                    "id": example["id"],
                    "persona": user.persona,
                    "expected_keep": example["expected_keep"],
                    "kept": kept,
                    "correct": kept == example["expected_keep"],
                    "report": report.model_dump(mode="json"),
                }
                verified.append(row)
                save(row)
                print(
                    example["id"],
                    report.status,
                    "kept" if kept else "excluded",
                    flush=True,
                )
        bad_before = sum(not row["expected_keep"] for row in verified)
        bad_after = sum(not row["expected_keep"] and row["kept"] for row in verified)
        survivors = sum(row["kept"] for row in verified)
        summary = {
            "label_reviewed": dataset["reviewed_by_user"],
            "label_provenance": dataset["provenance"],
            "fingerprint": fingerprint,
            "observations": str(path.relative_to(ROOT)),
            "environment": str(path.with_suffix(".environment.json").relative_to(ROOT)),
            "config": config.model_dump(mode="json"),
            "models": json.loads(
                (config.data_dir / "models/manifest.json").read_text()
            ),
            "hardware": {
                "platform": platform.platform(),
                "cpu": platform.processor(),
                "cpu_threads_configured": config.cpu_threads,
            },
            "git_commit": (
                await asyncio.to_thread(
                    subprocess.check_output,
                    ["git", "rev-parse", "HEAD"],
                    cwd=ROOT,
                    text=True,
                )
            ).strip(),
            "local_hardware_cost_usd": None,
            "paid_api_cost_usd": 0,
            "warmup": "No explicit warmup; sequential local calls include model loading where incurred",
            "retrieval": aggregate(observations),
            "verification": {
                "unit": "one_sentence_example_with_supplied_gold_source_evidence",
                "supported_retention_rate": sum(
                    row["expected_keep"] and row["kept"] for row in verified
                )
                / sum(row["expected_keep"] for row in verified)
                if any(row["expected_keep"] for row in verified)
                else None,
                "unsafe_removal_rate": sum(
                    not row["expected_keep"] and not row["kept"] for row in verified
                )
                / bad_before
                if bad_before
                else None,
                "examples": len(verified),
                "reviewed": claimset["reviewed_by_user"],
                "before_unsafe_sentence_rate": bad_before / len(verified)
                if verified
                else None,
                "after_unsafe_sentence_rate": bad_after / survivors
                if survivors
                else None,
                "retained": survivors,
                "unsafe_retained": bad_after,
                "correct_keep_decisions": sum(row["correct"] for row in verified),
                "needs_attention": sum(
                    row["report"]["status"] != "verified" for row in verified
                ),
            },
            "selection": "Pending the user's decision; V0 remains the development baseline",
        }
        (RESULTS / "rag_comparison.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
        )
        from evals.runners.rag_table import main as table

        table()
        print("Comparison saved; no active variant was changed", flush=True)
    finally:
        await runtime.close()


if __name__ == "__main__":
    asyncio.run(main())
