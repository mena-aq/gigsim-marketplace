"""Cheap live controls that reject a broken benchmark before generative inference."""

import copy
import json
from pathlib import Path

from data.client_matching import job_skills, required_skills
from evals.runners.rag_outcomes import simulate_outcome
from rag.config import RagConfig
from rag.models import Embeddings
from rag.types import RagFailure


def validate_pairs(cases: list[dict]) -> dict:
    """Detect incoherent public-job/hidden-client associations without changing them."""
    mismatched = [
        c["id"]
        for c in cases
        if not job_skills(c["job"]) & required_skills(c["client"])
    ]
    if mismatched:
        raise ValueError(
            f"{len(mismatched)}/{len(cases)} jobs have incompatible clients; run make rag-repair-data and use rag_jobs_v2.json"
        )
    if not cases:
        raise ValueError("Benchmark has no jobs")
    return {
        "jobs": len(cases),
        "compatible_pairs": len(cases),
        "low_hire_rate_clients": sum(c["client"]["hire_rate"] < 0.1 for c in cases),
    }


async def preflight(config: RagConfig, jobs_path: Path) -> dict:
    """Probe embedding boundary and real MCP reply gates in disposable databases."""
    cases = json.loads(jobs_path.read_text())["cases"]
    pairs = validate_pairs(cases)
    embeddings = Embeddings(config)
    runtime_limit = await embeddings.validate_runtime()
    # The installed MiniLM tokenizer encodes this word as a single token.
    vectors = await embeddings.embed(
        ["python " * (config.embedding_context_tokens - 2)]
    )
    if len(vectors) != 1 or len(vectors[0]) != config.embedding_dimensions:
        raise RagFailure(
            "embedding_response_invalid", "Preflight embedding shape is invalid"
        )
    control = next((c for c in cases if c["client"]["hire_rate"] >= 0.1), None)
    if control is None:
        raise ValueError("Benchmark has no non-bad-actor client for a reply control")
    draft = "I will use " + ", ".join(control["job"]["skills"]) + " for this project."
    positive = await simulate_outcome(control, draft, 42)
    negative_case = copy.deepcopy(control)
    negative_case["client"]["hidden_preferences"]["must_have_skills"] = [
        "unrelated-control-skill"
    ]
    negative = await simulate_outcome(negative_case, draft, 42)
    if not positive["reply"] or negative["status"] != "no_reply":
        raise ValueError(
            "GigSim control failed: matching draft must reach reply path; mismatched draft must be rejected"
        )
    return {
        "passed": True,
        "pairs": pairs,
        "runtime_embedding_context": runtime_limit,
        "configured_embedding_context": config.embedding_context_tokens,
        "embedding_input_tokens": config.embedding_context_tokens - 2,
        "controls": {
            "seed": 42,
            "matching": positive["status"],
            "mismatched": negative["status"],
        },
        "note": "Controls are diagnostic only; excluded from benchmark reply-rate observations",
    }
