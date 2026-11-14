"""Real-model RAG comparison; provisional labels, no automatic winner selection."""

import asyncio
import json
import platform
import subprocess
import time

from sqlalchemy import select

from apps.api.models import MCPCredential, User
from evals.runners.rag_metrics import aggregate, code_fingerprint, metrics
from mcp_servers.common.runtime import Runtime
from rag.config import ROOT, load_config
from rag.ingest.pipeline import read_manifest
from rag.retriever import Pipeline
from rag.types import Chunk, RagFailure
from rag.verify import verify_claims


async def run(args) -> None:
    """Measure retrieval and controlled claim regression fixtures for one RAG run."""
    results = args.output_dir
    config = load_config()
    dataset = json.loads(args.retrieval_dataset.read_text())
    claimset = json.loads(args.claim_dataset.read_text())
    if args.limit:
        dataset["queries"] = dataset["queries"][: args.limit]
        claimset["examples"] = claimset["examples"][: args.limit]
    runtime = Runtime()
    results.mkdir(parents=True, exist_ok=True)
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
        path = results / "rag_retrieval_observations.jsonl"
        existing = (
            [json.loads(line) for line in path.read_text().splitlines()]
            if path.exists()
            else []
        )
        if any(row["fingerprint"] != fingerprint for row in existing):
            raise SystemExit("Cannot resume: code, models, dataset, or index changed")
        identities = [(row["kind"], row["id"], row.get("variant")) for row in existing]
        expected = {
            ("retrieval", q["id"], v) for q in dataset["queries"] for v in args.variants
        }
        expected |= {("verification", e["id"], None) for e in claimset["examples"]}
        if len(set(identities)) != len(identities) or not set(identities) <= expected:
            raise ValueError(
                "Duplicate or unexpected retrieval/regression observations"
            )
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
                for variant in args.variants:
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
            "complete": True,
            "query_count": len(dataset["queries"]),
            "variants": args.variants,
            "label_reviewed": dataset["reviewed_by_user"],
            "label_provenance": dataset["provenance"],
            "fingerprint": fingerprint,
            "observations": str(path.resolve()),
            "environment": str(path.with_suffix(".environment.json").resolve()),
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
        (results / "rag_retrieval.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
        )
        print("Retrieval and claim regression fixtures saved", flush=True)
    finally:
        await runtime.close()
