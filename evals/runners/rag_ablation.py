"""Fresh V3 component ablation: full, without reranking, and without BM25."""

import argparse
import asyncio
import hashlib
import json
import time
from pathlib import Path

from sqlalchemy import select

from apps.api.models import MCPCredential, User
from evals.runners.rag_metrics import code_fingerprint
from evals.runners.rag_study import (
    StudyError,
    bootstrap,
    breakdowns,
    display_path,
    file_hash,
    load_dataset,
    paired_rows,
    rescore,
    write_reports,
)
from mcp_servers.common.runtime import Runtime
from rag.config import ROOT, load_config
from rag.ingest.pipeline import read_manifest
from rag.ranking import unique_items
from rag.retriever import Pipeline
from rag.types import Hit, RagFailure
from rag.variants.v2_hybrid import retrieve as hybrid
from rag.variants.v3_reranked import retrieve as reranked

CONFIGURATIONS = ("full_v3", "without_reranker", "without_bm25")


class NoGeneration:
    """A hard guard: these experiments must not invoke Qwen or another LLM."""

    def __init__(self):
        self.usage = []

    async def ask(self, *args, **kwargs):
        raise StudyError("Generative-model calls are forbidden in this ablation")


def snapshot_hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


async def run_configuration(
    query: str,
    pipeline: Pipeline,
    configuration: str,
    *,
    expected_manifest: str | None = None,
    k: int = 10,
) -> dict:
    """Use the same chunk pool limit, deduplication, and metrics for every arm."""
    if configuration not in CONFIGURATIONS:
        raise StudyError("Unknown ablation configuration")
    started = time.perf_counter()
    pipeline.diagnostics = {}
    await pipeline.prepare()
    if (
        expected_manifest is not None
        and snapshot_hash(pipeline.manifest) != expected_manifest
    ):
        raise StudyError("Index changed during the ablation; restart consistently")
    pool_size = pipeline.config.candidate_k
    if configuration == "full_v3":
        hits = await reranked(query, pipeline, pool_size)
    elif configuration == "without_reranker":
        hits = await hybrid(query, pipeline, pool_size)
    else:
        # Removing BM25 must retain the raw dense chunk pool, not V0's already
        # deduplicated document output; all arms rerank at the same stage.
        candidates = await pipeline.dense(query, pool_size)
        if candidates:
            scores = await asyncio.to_thread(
                pipeline.rerank, query, [hit.chunk.text for hit in candidates]
            )
            hits = sorted(
                [
                    Hit(chunk=hit.chunk, score=score)
                    for hit, score in zip(candidates, scores, strict=True)
                ],
                key=lambda hit: (-hit.score, hit.chunk.chunk_id),
            )
        else:
            hits = []
        pipeline.diagnostics["reranked_pairs"] = len(candidates)
    selected = unique_items(hits, k)
    return {
        "returned_ids": [hit.chunk.id for hit in selected],
        "seconds": time.perf_counter() - started,
        "diagnostics": pipeline.diagnostics,
        "error": None,
    }


def analyze_rows(rows: list[dict], dataset: dict) -> dict:
    queries = dataset["queries"]
    expected = {
        (query["id"], configuration)
        for query in queries
        for configuration in CONFIGURATIONS
    }
    keys = [(row["id"], row["configuration"]) for row in rows]
    if len(keys) != len(set(keys)) or set(keys) != expected:
        raise StudyError("Ablation requires one observation per query/configuration")
    if len({row.get("fingerprint") for row in rows}) != 1 or not rows[0].get(
        "fingerprint"
    ):
        raise StudyError("Ablation observations must share one fingerprint")
    labels = {query["id"]: query for query in queries}
    if any(
        row["persona"] != labels[row["id"]]["persona"]
        or row["query_type"] != labels[row["id"]]["type"]
        for row in rows
    ):
        raise StudyError("Ablation query metadata does not match the dataset")
    effects = {}
    for removed in CONFIGURATIONS[1:]:
        effects[removed] = bootstrap(paired_rows(rows, queries, "full_v3", removed))
    return {
        "primary_metric": "nDCG@10 on positive queries",
        "component_effects": effects,
        "delta_direction": "Full V3 minus ablated configuration; positive means the removed component helped",
        "breakdowns": breakdowns(rows, queries, CONFIGURATIONS),
        "labels_reviewed": dataset.get("reviewed_by_user", False),
        "selection": "Candidate V3 ablation only; production selection remains with the user",
        "generative_model_calls": 0,
        "timing_protocol": "Fresh context per query/configuration, no explicit warmup, configuration order rotated by query; model loading is included",
    }


async def main_async(args) -> None:
    config = load_config()
    dataset = load_dataset(args.dataset)
    claimset = json.loads(
        getattr(
            args, "claim_dataset", ROOT / "evals/datasets/claim_dev.json"
        ).read_text()
    )
    runtime = Runtime()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / "rag_ablation_observations.jsonl"
    try:
        async with runtime.sessions() as session:
            users = {
                user.persona: user
                for user in (
                    await session.execute(select(User).join(MCPCredential))
                ).scalars()
            }
        personas = {query["persona"] for query in dataset["queries"]}
        if not personas <= set(users):
            raise StudyError("Provision each dataset persona with make mcp-bootstrap")
        manifests = {
            persona: read_manifest(config, users[persona].id) for persona in personas
        }
        for query in dataset["queries"]:
            sources = {
                item["chunk"]["id"] for item in manifests[query["persona"]]["records"]
            }
            if not set(query["qrels"]) <= sources:
                raise StudyError("A labelled source is absent from its persona index")
        retrieval_fingerprint = code_fingerprint(config, manifests, dataset, claimset)
        wrapper_hash = hashlib.sha256(
            Path(__file__).read_bytes()
            + (ROOT / "evals/runners/rag_study.py").read_bytes()
            + (ROOT / "evals/runners/rag_eval.py").read_bytes()
            + (ROOT / "evals/runners/rag_metrics.py").read_bytes()
        ).hexdigest()
        fingerprint = hashlib.sha256(
            (retrieval_fingerprint + wrapper_hash).encode()
        ).hexdigest()
        manifest_hashes = {
            persona: snapshot_hash(manifest) for persona, manifest in manifests.items()
        }
        models = json.loads((config.data_dir / "models/manifest.json").read_text())
        if (
            models["embedding_digest"]
            != next(iter(manifests.values()))["embedding_digest"]
        ):
            raise StudyError("Installed model metadata differs from the indexed model")
        rows = (
            [json.loads(line) for line in path.read_text().splitlines()]
            if path.exists()
            else []
        )
        keys = [(row["id"], row["configuration"]) for row in rows]
        expected = {(q["id"], c) for q in dataset["queries"] for c in CONFIGURATIONS}
        if len(set(keys)) != len(keys) or not set(keys) <= expected:
            raise StudyError("Duplicate or unexpected ablation observations")
        if any(row["fingerprint"] != fingerprint for row in rows):
            raise StudyError(
                "Cannot resume ablation: model/index/code/fixtures changed"
            )
        with path.open("a") as output:
            for offset, query in enumerate(dataset["queries"]):
                # Counterbalance shared-cache and execution-order effects without
                # claiming this shared development CPU is controlled hardware.
                pivot = offset % len(CONFIGURATIONS)
                order = CONFIGURATIONS[pivot:] + CONFIGURATIONS[:pivot]
                for configuration in order:
                    if (query["id"], configuration) in keys:
                        continue
                    user = users[query["persona"]]
                    pipeline = Pipeline(
                        config,
                        runtime.settings.mcp_persona_dir,
                        user.id,
                        user.persona,
                        llm=NoGeneration(),
                    )
                    started = time.perf_counter()
                    try:
                        observation = await run_configuration(
                            query["query"],
                            pipeline,
                            configuration,
                            expected_manifest=manifest_hashes[user.persona],
                        )
                    except RagFailure as exc:
                        if exc.code in (
                            "index_incompatible",
                            "index_stale",
                            "index_missing",
                            "forbidden",
                            "model_unavailable",
                        ):
                            raise StudyError(
                                "Index/model prerequisites changed or are missing; fix them before restarting"
                            ) from exc
                        observation = {
                            "returned_ids": [],
                            "seconds": time.perf_counter() - started,
                            "diagnostics": pipeline.diagnostics,
                            "error": {"code": exc.code, "message": exc.message},
                        }
                    row = {
                        "id": query["id"],
                        "persona": query["persona"],
                        "query_type": query["type"],
                        "configuration": configuration,
                        "fingerprint": fingerprint,
                        **observation,
                    }
                    row["metrics"] = rescore(row, query)
                    rows.append(row)
                    output.write(json.dumps(row, ensure_ascii=False) + "\n")
                    output.flush()
                    print(
                        query["id"],
                        configuration,
                        "ok" if row["error"] is None else row["error"]["code"],
                        round(row["seconds"], 2),
                        flush=True,
                    )
        summary = analyze_rows(rows, dataset)
        summary.update(
            fingerprint=fingerprint,
            retrieval_fingerprint=retrieval_fingerprint,
            experiment_code_sha256=wrapper_hash,
            dataset_sha256=file_hash(args.dataset),
            observations=display_path(path),
            config=config.model_dump(mode="json"),
            models=models,
        )
        text = (
            "# R&D B: V3 component ablation\n\n"
            "Full V3 = dense + BM25 + reranking. Remove exactly one added component "
            "per comparison. The dense backbone is retained.\n\n"
            "These configurations are experimental wrappers, not additional RAG variants. "
            "All three arms were measured fresh with the same candidate limit. "
            "No Qwen grading, decomposition, or verification calls are used.\n\n"
            "Quality metrics exclude no-evidence queries; abstention is reported separately. "
            "Failures count as zero quality, not successful abstention. Labels are provisional "
            "until reviewed. Per-persona/type summaries and full-minus-ablated paired "
            "effects are in the JSON report. Production selection remains with the user."
        )
        text += "\n\n## Paired component effects\n\n"
        for removed, effect in summary["component_effects"].items():
            text += f"- Full V3 minus {removed}: mean nDCG@10 difference {effect['mean_delta']:.4f}, 95% bootstrap interval {effect['ci95']}.\n"
        write_reports(args.output_dir, "rag_ablation", summary, rows, dataset, text)
        print(f"Wrote {display_path(args.output_dir / 'rag_ablation.md')}")
    finally:
        await runtime.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", type=Path, default=ROOT / "evals/datasets/rag_dev.json"
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT / "evals/results")
    args = parser.parse_args(argv)
    try:
        asyncio.run(main_async(args))
    except (StudyError, RagFailure, OSError, ValueError) as exc:
        parser.exit(1, f"Ablation stopped: {exc}\n")


if __name__ == "__main__":
    main()
