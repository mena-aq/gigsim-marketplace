"""Internal RAG drafting, verification, quality, and simulated-outcome stages."""

import hashlib
import json
import random
import re
import time
from pathlib import Path
from statistics import mean

from pydantic import BaseModel, Field
from sqlalchemy import select

from apps.api.models import MCPCredential, User
from evals.runners.rag_diagnostics import failure_diagnostics
from evals.runners.rag_environment import capture_environment
from evals.runners.rag_metrics import code_fingerprint, percentile
from evals.runners.rag_outcomes import simulate_outcome
from mcp_servers.common.runtime import Runtime
from rag.config import ROOT, VARIANTS, load_config
from rag.ingest.pipeline import read_manifest
from rag.llm import StructuredLLM
from rag.retriever import Pipeline
from rag.types import RagFailure
from rag.verify import DraftJudgment, plain_nonexperience, sentence_spans, verify_claims


class Draft(BaseModel):
    sentences: list[str] = Field(min_length=1, max_length=3)

    @property
    def draft(self) -> str:
        return " ".join(self.sentences)


class JudgeScore(BaseModel):
    score: int = Field(ge=1, le=5, strict=True)


async def assess_draft(text: str, evidence: list, llm) -> dict:
    """Audit independently without applying the verifier's retention policy."""
    spans = sentence_spans(text)
    aliases = {f"E{i + 1}": chunk.chunk_id for i, chunk in enumerate(evidence)}
    sentences = []
    raw_judgments = []
    for offset, (start, end) in enumerate(spans):
        kind = (
            "intent" if plain_nonexperience(text[start:end], "intent") else "nonfactual"
        )
        if plain_nonexperience(text[start:end], kind):
            sentences.append(
                {
                    "index": offset,
                    "text": text[start:end],
                    "claims": [
                        {
                            "text": text[start:end],
                            "kind": kind,
                            "status": "supported",
                            "evidence_ids": [],
                            "reason": "Plain nonexperience expression",
                        }
                    ],
                }
            )
    excluded = {s["index"] for s in sentences}
    try:
        for offset in range(0, len(spans), 4):
            batch = [
                (i, spans[i])
                for i in range(offset, min(offset + 4, len(spans)))
                if i not in excluded
            ]
            if not batch:
                continue
            response = await llm.ask(
                "rag_eval_assess",
                {
                    "sentences": [
                        {"index": i, "text": text[start:end]}
                        for i, (start, end) in batch
                    ],
                    "evidence": [
                        {"id": key, "text": chunk.text}
                        for key, chunk in zip(aliases, evidence, strict=True)
                    ],
                },
                DraftJudgment,
            )
            raw_judgments.append(response.model_dump(mode="json"))
            if sorted(s.index for s in response.sentences) != [i for i, _ in batch]:
                raise RagFailure("assessment_invalid", "Missing or duplicate sentence")
            for sentence in response.sentences:
                start, end = spans[sentence.index]
                covered = [False] * (end - start)
                for claim in sentence.claims:
                    location = text[start:end].find(claim.text)
                    if (
                        not claim.text.strip()
                        or location < 0
                        or any(key not in aliases for key in claim.evidence_ids)
                    ):
                        raise RagFailure(
                            "assessment_invalid", "Invented claim or citation"
                        )
                    if (
                        claim.kind == "experience"
                        and claim.status != "unsupported"
                        and not claim.evidence_ids
                    ):
                        raise RagFailure(
                            "assessment_invalid", "Missing experience evidence"
                        )
                    if claim.kind != "experience" and (
                        claim.status != "supported"
                        or not plain_nonexperience(claim.text, claim.kind)
                    ):
                        raise RagFailure(
                            "assessment_invalid", "Inconsistent factual classification"
                        )
                    covered[location : location + len(claim.text)] = [True] * len(
                        claim.text
                    )
                    claim.evidence_ids = [aliases[key] for key in claim.evidence_ids]
                residual = "".join(
                    c if not covered[i] else " " for i, c in enumerate(text[start:end])
                )
                if re.sub(
                    r"\b(?:and|or|but)\b|[\W_]", "", residual, flags=re.IGNORECASE
                ):
                    raise RagFailure("assessment_invalid", "Unchecked proposal text")
                sentences.append(
                    {
                        "text": text[start:end],
                        "claims": [c.model_dump() for c in sentence.claims],
                    }
                )
    except RagFailure as exc:
        return {
            "status": "needs_attention",
            "sentences": sentences,
            "error": exc.code,
            "message": exc.message,
            "raw_judgments": raw_judgments,
        }
    return {
        "status": "verified",
        "sentences": sentences,
        "raw_judgments": raw_judgments,
    }


def sha(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def prepare_dataset(path: Path) -> None:
    """Freeze a balanced, seeded sample before any proposal measurements."""
    if path.exists():
        raise ValueError("Dataset exists; preserve it or choose another path")
    jobs = json.loads((ROOT / "data/processed/jobs.json").read_text())
    clients = {
        c["id"]: c
        for c in json.loads((ROOT / "data/processed/clients.json").read_text())
    }
    categories = {
        "ml_engineer": "AI & Machine Learning",
        "fullstack_dev": "Web Development",
        "data_analyst": "Data Science",
    }
    rng = random.Random(42)
    cases = []
    for persona, category in categories.items():
        eligible = sorted(
            [
                job
                for job in jobs
                if job["category"] == category
                and not job.get("is_scam")
                and not job.get("has_injection")
                and job.get("client_id") in clients
                and len(job["description"]) <= 3000
            ],
            key=lambda job: job["id"],
        )
        for job in rng.sample(eligible, 10):
            cases.append(
                {
                    "id": job["id"],
                    "persona": persona,
                    "job": job,
                    "client": clients[job["client_id"]],
                }
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "seed": 42,
                "label_provenance": "Seeded processed-job sample; no evidence qrels for these jobs",
                "selection": "10 non-scam, non-injection jobs per mapped category; description <=3000 chars",
                "source_jobs_sha256": sha(jobs),
                "source_clients_sha256": sha(clients),
                "cases": cases,
            },
            indent=2,
        )
        + "\n"
    )


def claim_counts(report: dict) -> dict:
    """Count independently assessed atomic experience claims only."""
    if report["status"] != "verified":
        raise ValueError("Incomplete independent assessment")
    claims = [
        claim
        for sentence in report["sentences"]
        for claim in sentence["claims"]
        if claim["kind"] == "experience"
    ]
    return {
        "experience": len(claims),
        "unsupported": sum(c["status"] == "unsupported" for c in claims),
        "partly_supported": sum(c["status"] == "partly_supported" for c in claims),
        "supported_texts": [c["text"] for c in claims if c["status"] == "supported"],
    }


async def evaluate_case(case: dict, variant: str, pipeline: Pipeline, config) -> dict:
    """Run one measured proposal; failures retain diagnostic observations."""
    row = {
        "id": case["id"],
        "persona": case["persona"],
        "category": case["job"]["category"],
        "variant": variant,
        "error": None,
        "assessment_error": None,
        "outcome_error": None,
        "usage": {},
        "timings": {},
    }
    start = time.perf_counter()
    try:
        job = case["job"]
        query = job["title"] + "\n" + job["description"]
        print("  retrieve", flush=True)
        row["usage"]["retrieval"] = pipeline.llm.usage
        result = await pipeline.retrieve(query, 5, variant=variant)
        chunks = [hit.chunk for hit in result.hits]
        row["retrieval"] = result.model_dump(mode="json")
        row["usage"]["retrieval"] = pipeline.llm.usage
        evidence = [{"id": f"E{i + 1}", "text": c.text} for i, c in enumerate(chunks)]
        writer = StructuredLLM(config)
        print("  draft", flush=True)
        row["usage"]["writer"] = writer.usage
        draft = await writer.ask(
            "rag_eval_writer",
            {
                "job": {key: job[key] for key in ("title", "description", "skills")},
                "evidence": evidence,
                "word_limit": config.proposal_words,
            },
            Draft,
        )
        row["draft"] = draft.draft
        row["usage"]["writer"] = writer.usage
        verifier = StructuredLLM(config)
        print("  verify", flush=True)
        row["usage"]["verifier"] = verifier.usage
        report = await verify_claims(draft.draft, chunks, verifier)
        row["verification"] = report.model_dump(mode="json")
        row["cleaned_draft"] = report.cleaned_draft
        row["usage"]["verifier"] = verifier.usage
        row["timings"]["proposal_seconds"] = time.perf_counter() - start
        # No verifier output or labels are passed to the independent assessor.
        for label, text in (("before", draft.draft), ("after", report.cleaned_draft)):
            assessor = StructuredLLM(config)
            print("  assess " + label, flush=True)
            row[label + "_assessment"] = await assess_draft(text, chunks, assessor)
            row["usage"][label + "_assessment"] = assessor.usage
            try:
                row[label + "_counts"] = claim_counts(row[label + "_assessment"])
            except ValueError:
                row["assessment_error"] = (
                    "Independent assessment incomplete; excluded from claim metrics"
                )
        if report.cleaned_draft:
            judge = StructuredLLM(config)
            print("  judge", flush=True)
            try:
                row["judge_score_uncalibrated"] = (
                    await judge.ask(
                        "rag_eval_judge",
                        {
                            "job": {
                                key: job[key]
                                for key in ("title", "description", "skills")
                            },
                            "proposal": report.cleaned_draft,
                            "evidence": evidence,
                        },
                        JudgeScore,
                    )
                ).score
            except RagFailure as exc:
                row["judge_error"] = exc.code
            row["usage"]["judge"] = judge.usage
        print("  isolated MCP outcome", flush=True)
        outcome_start = time.perf_counter()
        try:
            seed = 42 + int(hashlib.sha256(case["id"].encode()).hexdigest()[:8], 16)
            row["outcome"] = await simulate_outcome(case, report.cleaned_draft, seed)
        except RuntimeError as exc:
            row["outcome_error"] = type(exc).__name__
        row["timings"]["outcome_seconds"] = time.perf_counter() - outcome_start
    except RagFailure as exc:
        row["error"] = {"code": exc.code, "message": exc.message}
    row["timings"]["total_eval_seconds"] = time.perf_counter() - start
    return row


def summarize(rows: list[dict]) -> dict:
    """Aggregate with explicit denominators; failed observations never become zeros."""
    result = {}
    groups = {"all": rows}
    for key in ("persona", "category"):
        for value in sorted({r[key] for r in rows}):
            groups[key + ":" + value] = [r for r in rows if r[key] == value]
    for group, selected in groups.items():
        result[group] = {}
        for variant in VARIANTS:
            arm = [r for r in selected if r["variant"] == variant]
            if not arm:
                continue
            completed = [r for r in arm if r["error"] is None]
            assessed = [
                r
                for r in completed
                if not r["assessment_error"] and "after_counts" in r
            ]
            before = sum(r["before_counts"]["experience"] for r in assessed)
            after = sum(r["after_counts"]["experience"] for r in assessed)
            before_bad = sum(r["before_counts"]["unsupported"] for r in assessed)
            after_bad = sum(r["after_counts"]["unsupported"] for r in assessed)
            before_supported = [
                (r, c) for r in assessed for c in r["before_counts"]["supported_texts"]
            ]
            outcomes = [r["outcome"] for r in completed if r.get("outcome")]
            submitted = [o for o in outcomes if o["submitted"]]
            seconds = [r["timings"]["proposal_seconds"] for r in completed]
            usage = [u for r in arm for stage in r["usage"].values() for u in stage]
            proposal_usage = [
                u
                for r in arm
                for name, stage in r["usage"].items()
                if name in {"retrieval", "writer", "verifier"}
                for u in stage
            ]
            result[group][variant] = {
                **failure_diagnostics(arm),
                "attempted": len(arm),
                "completed": len(completed),
                "failures": len(arm) - len(completed),
                "assessed_proposals": len(assessed),
                "before_experience_claims": before,
                "after_experience_claims": after,
                "before_unsupported_claims": before_bad,
                "after_unsupported_claims": after_bad,
                "before_unsupported_rate": before_bad / before if before else None,
                "after_unsupported_rate": after_bad / after if after else None,
                "unsupported_claims_per_proposal": after_bad / len(assessed)
                if assessed
                else None,
                "partly_supported_claims_after": sum(
                    r["after_counts"]["partly_supported"] for r in assessed
                ),
                "supported_retention_rate": sum(
                    c in r["after_counts"]["supported_texts"]
                    for r, c in before_supported
                )
                / len(before_supported)
                if before_supported
                else None,
                "empty_drafts": sum(not r.get("cleaned_draft", "") for r in completed),
                "needs_attention": sum(
                    r["verification"]["status"] != "verified" for r in completed
                ),
                "outcome_observations": len(outcomes),
                "submitted": len(submitted),
                "replies": sum(o["reply"] for o in submitted),
                "hires": sum(o["hire"] for o in submitted),
                "reply_rate": mean(o["reply"] for o in submitted)
                if submitted
                else None,
                "hire_rate": mean(o["hire"] for o in submitted) if submitted else None,
                "reply_yield_per_attempt": sum(o["reply"] for o in outcomes) / len(arm),
                "outcome_failures": sum(
                    r["outcome_error"] is not None for r in completed
                ),
                "p50_proposal_seconds": percentile(seconds, 0.5),
                "p95_proposal_seconds": percentile(seconds, 0.95),
                "proposal_prompt_tokens": sum(
                    u["prompt_tokens"] for u in proposal_usage
                ),
                "proposal_completion_tokens": sum(
                    u["completion_tokens"] for u in proposal_usage
                ),
                "evaluation_prompt_tokens": sum(u["prompt_tokens"] for u in usage),
                "evaluation_completion_tokens": sum(
                    u["completion_tokens"] for u in usage
                ),
                "paid_api_cost_per_completed_proposal_usd": 0 if completed else None,
                "total_cost_per_proposal_usd": None,
                "judge_score": None,
                "judge_status": "pending_human_calibration",
            }
    return result


def validate_resume(
    rows: list[dict], expected: set[tuple[str, str]], fingerprint: str
) -> None:
    """Reject duplicate/foreign observations and incompatible experiments."""
    keys = [(row["id"], row["variant"]) for row in rows]
    if len(set(keys)) != len(keys) or not set(keys) <= expected:
        raise ValueError("Duplicate or unexpected observations")
    if any(row["fingerprint"] != fingerprint for row in rows):
        raise ValueError(
            "Cannot resume: configuration, code, dataset or index changed; use a new output directory"
        )


async def run(args) -> None:
    config = load_config()
    dataset = json.loads(args.jobs_dataset.read_text())
    cases = dataset["cases"][: args.limit] if args.limit else dataset["cases"]
    runtime = Runtime()
    try:
        async with runtime.sessions() as session:
            users = {
                u.persona: u
                for u in (
                    await session.execute(select(User).join(MCPCredential))
                ).scalars()
            }
        for persona in {c["persona"] for c in cases}:
            if persona not in users:
                raise ValueError(
                    "Missing provisioned MCP persona; run make mcp-bootstrap"
                )
        if len({case["id"] for case in cases}) != len(cases):
            raise ValueError("Evaluation job IDs must be unique")
        manifests = {
            p: read_manifest(config, users[p].id) for p in {c["persona"] for c in cases}
        }
        base = code_fingerprint(config, manifests, dataset, {})
        files = sorted((ROOT / "evals/runners").glob("rag*.py"))
        files += sorted((ROOT / "agent/prompts").glob("rag_eval*.md"))
        files += sorted((ROOT / "gigsim").glob("*.py"))
        files += sorted((ROOT / "gigsim/routers").glob("*.py"))
        files += sorted((ROOT / "mcp_servers").rglob("*.py"))
        fingerprint = sha(
            {
                "base": base,
                "files": {
                    str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in files
                },
                "limit": args.limit,
                "variants": args.variants,
            }
        )
        args.output_dir.mkdir(parents=True, exist_ok=True)
        path = args.output_dir / "rag_workflow_observations.jsonl"
        rows = (
            [json.loads(line) for line in path.read_text().splitlines()]
            if path.exists()
            else []
        )
        expected = {
            (case["id"], variant) for case in cases for variant in args.variants
        }
        validate_resume(rows, expected, fingerprint)
        keys = {(r["id"], r["variant"]) for r in rows}
        await capture_environment(
            config, args.output_dir / "rag_workflow.environment.json", fingerprint
        )
        (args.output_dir / "rag_jobs.json").write_text(
            json.dumps(dataset, indent=2) + "\n"
        )

        def publish_progress():
            summary = {
                "fingerprint": fingerprint,
                "dataset_sha256": sha(dataset),
                "complete": {(r["id"], r["variant"]) for r in rows} == expected,
                "population": "Frozen proposal jobs; retrieval qrels remain a separate dataset",
                "claim_labels": "Independent same-model assessment; provisional, not human validated",
                "latency": "Retrieval, writer and verifier wall time; excludes assessor, judge and simulator wait",
                "cost": "Local inference: paid API spend zero; hardware/electricity unmeasured",
                "simulator": "Disposable SQLite, real MCP, quotas/chaos disabled, paired per-job seed; hidden preferences unchanged",
                "results": summarize(rows),
            }
            (args.output_dir / "rag_workflow.json").write_text(
                json.dumps(summary, indent=2) + "\n"
            )

        with path.open("a") as handle:
            for i, case in enumerate(cases):
                # Rotate arm order to reduce fixed model-loading/order bias.
                variants = (
                    args.variants[i % len(args.variants) :]
                    + args.variants[: i % len(args.variants)]
                )
                for variant in variants:
                    if (case["id"], variant) in keys:
                        continue
                    print(
                        f"{len(rows) + 1}/{len(cases) * len(variants)} {case['persona']} {case['id']} {variant}",
                        flush=True,
                    )
                    pipeline = Pipeline(
                        config,
                        runtime.settings.mcp_persona_dir,
                        users[case["persona"]].id,
                        case["persona"],
                    )
                    row = await evaluate_case(case, variant, pipeline, config)
                    row["fingerprint"] = fingerprint
                    handle.write(json.dumps(row) + "\n")
                    handle.flush()
                    rows.append(row)
                    publish_progress()
        publish_progress()
    finally:
        await runtime.close()
