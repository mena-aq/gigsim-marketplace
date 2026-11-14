# GigBid — Freelancer Copilot

GigBid is being built to discover freelance jobs, assess fit and risk, and draft
proposals grounded in portfolio evidence. A human must approve every proposal,
message, and Connects spend. Development uses our separate GigSim marketplace.

## Current state

Step 0 supplies GigSim, data processing, persona generation, and simulator tests.
Step 1 adds a Next.js/TypeScript web shell, FastAPI liveness/readiness endpoints,
Arq worker, six tenant-owned PostgreSQL tables with Alembic migrations, Redis,
Chroma, and a bridge to the existing host Ollama/qwen2.5:3b. Step 2 adds authenticated Portfolio/Marketplace/Workspace MCP services, durable
write receipts, approval enforcement, and a persistent local Workspace mock.
Part C adds durable bid/conversation graphs, Postgres checkpoint and memory
stores, queued worker recovery, and an authenticated review workspace at `/review`.
Full product onboarding and the remaining business screens are later milestones.
See [the orchestration guide](docs/ORCHESTRATION.md) for review, replay and tests.

## Run locally

Prerequisites: Docker with Compose, and uv. Node 22/npm are needed for host web
commands; container builds include Node.

```bash
cp .env.example .env  # only if you do not already have .env
uv sync --frozen --extra dev
make dev
```

Preserve an existing `.env` and add missing keys from `.env.example`. Open
http://localhost:3000; API documentation is at http://localhost:8000/docs.
`docker compose up --build -d` also works from the root. No model download or
marketplace submission happens on startup. GigSim data is seeded explicitly
with `make seed` after processing; see its README for Step 0 commands.

```bash
make test           # isolated tests; Postgres integration is opt-in
make lint
make worker-smoke   # proves separate worker execution via Redis
make web-install
make api-client     # regenerate typed API contract
make web-check
make down           # preserve persistent volumes
```

Python versions are resolved in `uv.lock`; frontend versions are pinned in
`apps/web/package.json` and `package-lock.json`. Use `uv sync --frozen` and
`npm ci` to reproduce them. The frontend uses Next.js 16 and React 19 on Node 22.

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [stack decision](docs/adr/001-foundation.md)
- [Runbook](docs/RUNBOOK.md): setup, migrations, ports, and verification
- [GigSim](gigsim/README.md) and [data card](docs/DATA_CARD.md)
- [Implementation checklist](docs/IMPLEMENTATION_CHECKLIST.md)
- [AI usage disclosure](docs/AI_USAGE.md)

## Project rules

All agent capabilities will be MCP tools; marketplace access uses one port with
simulator and official live adapters. No scraping. Job posts and messages are
untrusted input. Claims must have portfolio evidence. Prompts and policy belong
in files/configuration. Secrets and hidden evaluation data never enter Git;
measured evaluation outputs will be committed. No business data is publicly
exposed by the foundation endpoints.

## MCP layer

See [the tool inventory](docs/TOOLS.md) and [Portfolio server installation](mcp_servers/portfolio/README.md).
Provision distinct MCP tokens in `.env`, run `make migrate`, `make mcp-bootstrap`,
then `make dev` and `make mcp-smoke`. Only previews/local drafts are available
until a human grants approval in the review workspace. Marketplace integration is GigSim-only;
Upwork is excluded and GitHub is deferred by project choice.

## RAG pipeline

Step 3 implements exactly V0 (dense), V1 (decomposed), V2 (hybrid), V3 (reranked),
and V8 (bounded corrective retrieval), plus incremental local ingestion and
read-only claim verification through Portfolio MCP. Existing host Ollama runs
all-minilm embeddings and Qwen; the reranker uses CPU ONNX.

For fresh setup run `make rag-models` and `make rag-ingest`. Run
`make rag-repair-data` to prepare coherent client fixtures, then `make rag-eval`. One evaluation
covers all five variants: retrieval, drafting, claim verification, judging,
simulated replies, and component ablation. Future runs can take hours on CPU. They use the repaired v2 job snapshot and
preflight embedding/runtime and simulator checks. Existing published numbers are
historical until you complete a new run.

`make rag-table` regenerates the exact B5 CSV, Markdown, and this README from saved
measurements without model calls. The active [CSV](evals/results/rag_comparison.csv)
and [report](evals/results/rag_comparison.md) cite their raw evidence. Existing
measurements and your 30 human scores have been imported without rerunning models.
`make rag-calibrate` imports one overall 1–5 score per item and reports agreement
alongside judge means, including low agreement. V0 remains the development baseline;
no shipped variant has been selected.

See [the evaluation protocol](docs/RAG_EXPERIMENT.md) and [runbook](docs/RUNBOOK.md).

<!-- B3_B5_START -->
## RAG evaluation — B3, B5 and ablation

Run status: complete. Workflow: RAG benchmark.

One evaluation covers retrieval, drafting, claim verification, quality judging, and simulated replies. The imported measurements use labelled retrieval queries and a fixed GigSim job set; they are separate fixtures, not paired observations of the same jobs. p95 covers retrieval → drafting → verification and excludes assessment, judging and simulator waiting. Paid API spend is zero for local inference; total hardware cost is unmeasured.

Judge calibration: 30 human scores; exact agreement 10.0%; Cohen's κ = 0.031. Judge means are published alongside agreement; low agreement makes them provisional.

| Variant | Evidence Recall@5 | nDCG@10 | Unsupported claims per proposal | Judge score | GigSim reply rate | p95 latency (s) | Cost per proposal (USD) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| v0 | 0.815 | 0.738 | 0.000 | 3.692 | 0.000 | 119.263 | not measured |
| v1 | 0.704 | 0.625 | 0.000 | 3.857 | 0.000 | 151.708 | not measured |
| v2 | 0.907 | 0.869 | 0.000 | 3.375 | 0.000 | 118.413 | not measured |
| v3 | 0.944 | 0.914 | 0.000 | 3.571 | 0.000 | 125.371 | not measured |
| v8 | 0.815 | 0.787 | 0.000 | 3.714 | 0.000 | 245.830 | not measured |

### Claim verification and outcome denominators

| Variant | Assessed drafts | Unsupported before | Unsupported after | Supported retention | Failures | Submitted | Replies |
| --- | --- | --- | --- | --- | --- | --- | --- |
| v0 | 13 | 0/4 (0.000) | 0/4 (0.000) | 0.500 | 11 | 13 | 0 |
| v1 | 8 | 0/0 (not measured) | 0/0 (not measured) | not measured | 12 | 7 | 0 |
| v2 | 7 | 0/3 (0.000) | 0/2 (0.000) | 1.000 | 11 | 8 | 0 |
| v3 | 10 | 0/3 (0.000) | 0/1 (0.000) | 0.500 | 11 | 7 | 0 |
| v8 | 8 | 0/6 (0.000) | 0/2 (0.000) | 0.333 | 13 | 7 | 0 |

Unsupported rates use independently assessed atomic experience claims; partly supported claims and incomplete assessments are recorded in JSON. An empty denominator is undefined. A zero unsupported count with few assessed claims does not establish zero hallucination risk. Supported retention uses exact claim text and may be affected by segmentation.

Reply rate = replied/interview/hired outcomes divided by submitted proposals with completed outcomes. Empty drafts and failed submissions are excluded from that denominator; JSON also records reply yield per attempted job, empty drafts, and outcome failures. GigSim runs in fresh in-memory fixtures through real MCP tools, with the same job/client/random seed for each variant and skill mentions derived from the cleaned text. It checks skill mentions, generic openings and randomness, not semantic proposal quality.

### Failure and reply-gate breakdown

| Variant | Embedding failures | Decomposition failures | Other model failures | Verifier errors | Assessment failures | Skill rejects | Eligible no-reply |
| --- | --- | --- | --- | --- | --- | --- | --- |
| v0 | 11 | 0 | 0 | 5 | 6 | 13 | 0 |
| v1 | 0 | 12 | 0 | 7 | 10 | 7 | 0 |
| v2 | 11 | 0 | 0 | 8 | 12 | 8 | 0 |
| v3 | 11 | 0 | 0 | 11 | 9 | 7 | 0 |
| v8 | 11 | 0 | 2 | 8 | 9 | 7 | 0 |

Verifier/assessment errors may overlap a completed draft and are not added to job failures. Historical reply gates are reconstructed from the saved job/client/draft; this does not change the recorded outcome.

### Component ablation

Full V3 = dense + BM25 + reranking. Positive full-minus-ablated deltas favor the retained component. This retrieval-only component test runs within rag-eval; it does not generate extra proposals.

| Component removed | Paired nDCG@10 delta | 95% bootstrap interval |
| --- | --- | --- |
| without_reranker | 0.0449 | [0.00509537794236128, 0.09167322659866547] |
| without_bm25 | 0.0098 | [0.0, 0.02934090250806566] |

Per-persona/category results, MRR, p50, tokens, partial support, hire rate and failures are in the JSON. The production agent graph and blind pairwise classmate panel remain future work. No shipped variant has been selected.

Sources:

- [rag_retrieval.json](evals/results/rag_retrieval.json)
- [rag_retrieval_observations.jsonl](evals/results/rag_retrieval_observations.jsonl)
- [rag_workflow.json](evals/results/rag_workflow.json)
- [rag_workflow_observations.jsonl](evals/results/rag_workflow_observations.jsonl)
- [rag_jobs.json](evals/results/rag_jobs.json)
- [rag_judge_calibration.json](evals/results/rag_judge_calibration.json)
- [rag_human_review.csv](evals/results/rag_human_review.csv)
- [rag_ablation.json](evals/results/rag_ablation.json)
- [rag_import.json](evals/results/rag_import.json)

The completed [V2–V3 R&D hypothesis study](evals/results/rag_rd_b.md) remains separate and is not rerun by rag-eval.
<!-- B3_B5_END -->
