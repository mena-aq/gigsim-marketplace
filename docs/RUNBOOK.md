# Local foundation runbook

Part C execution, approval, recovery and checkpoint replay instructions are in
[ORCHESTRATION.md](ORCHESTRATION.md). Run `make migrate` after updating dependencies
to initialize the graph outbox and LangGraph-owned checkpoint/memory tables.
The minimal authenticated operator workspace is at `/review`.

## First run

Prerequisites: Docker Engine with Compose, uv, and Node 22 with npm for local web
commands. Docker builds do not require host Node. From the repository root:

```bash
cp .env.example .env  # only when .env does not already exist
uv sync --extra dev
make dev
# Or: docker compose up --build -d
```

Open http://localhost:3000. API docs: http://localhost:8000/docs. The web shell
shows real readiness; no sign-in or business workflow exists yet. Compose starts
GigSim, its database, GigBid Postgres, Redis, migration job, API, worker, Chroma,
and an Ollama bridge to your host service. `make down` preserves volumes. Do not use `down -v` unless deliberately
resetting disposable data. Database defaults are for local development only.

Keep existing `.env` credentials. Upgrade a starter `DATABASE_URL` using
`postgresql+psycopg://` to `postgresql+asyncpg://`. Add missing keys from `.env.example`; never
commit `.env`. Compose overrides network URLs to use service names. Host tools
use localhost: Postgres 5432, GigSim Postgres 5433, Redis 6379, API 8000,
GigSim 8081, Chroma 8001, Ollama 11434. Internal Chroma listens on 8000.
Use URL-encoded database credentials if they contain URL-reserved characters.

## Checks and development

```bash
make test
make worker-smoke
make web-install
make api-client
make web-check
make api           # host API with reload
make worker        # host worker, needs Redis
make migrate       # host migration, needs GigBid Postgres
```

`make worker-smoke` enqueues through Redis and waits for the separate worker.
API readiness can be checked with `curl -f http://localhost:8000/ready`.
Stop Redis to see readiness return 503; reload the web shell for its unavailable
state. Restart Redis to recover. No background browser polling is implemented.
Use `docker compose --env-file .env -f infra/docker-compose.yml logs api worker migrate`
when startup fails. Readiness responses deliberately omit connection errors.

To verify schema constraints against a disposable database, migrate it, then run:

```bash
FOUNDATION_TEST_DATABASE_URL=postgresql+asyncpg://gigbid:gigbid@localhost:5432/foundation_test \
  uv run pytest tests/integration/test_foundation_postgres.py -q
```

The test rolls back inserted rows. Never point tests at a production database.
Migration revisions are committed; autogenerate new revisions after model changes,
review them, and apply with Alembic. API startup does not create tables implicitly.

## Data and models

Existing Step 0 data commands remain available: `make process`, `make personas`,
`make seed`, `make smoke`. Seeding is explicit; Compose does not automatically
seed GigSim. The processed data directory must contain the seed JSON files.
Do not reset or regenerate existing data to start the foundation.

The local Ollama service already has `qwen2.5:3b`. The Linux-only `ollama`
Compose service runs a small TCP bridge on Docker's host gateway at port 11435,
forwarding to the existing host listener at 127.0.0.1:11434. API and worker use
`http://host.docker.internal:11435`; host commands keep using localhost:11434.
This does not copy models, start another model runtime, or change host Ollama's
binding. The bridge binds only Docker's host gateway, not all host interfaces.
Start your host Ollama before using models. The model remains provisional until
later evaluations; this milestone does not route agent nodes to it yet.

This bridge configuration targets Linux Docker Engine. On Docker Desktop,
configure containers to use its host-service access instead. Do not pull the
large Ollama image just to duplicate a model already installed on the host.

## Deferred operations

Scouting schedules, conservative live polling, retries/dead letters, tracing,
reviewer provisioning, and public deployment belong to later milestones.

## Step 2: MCP services

Three owned servers start with Compose: Portfolio on localhost:8101/mcp,
Marketplace on localhost:8102/mcp, Workspace on localhost:8103/mcp. Each has a
public `/health` liveness endpoint; `/mcp` requires bearer authentication.
No Upwork or GitHub connection is needed. Host Ollama is unchanged and is not
used by deterministic Step 2 tools.

Add three distinct random MCP_TOKEN_ML_ENGINEER, MCP_TOKEN_FULLSTACK_DEV, and
MCP_TOKEN_DATA_ANALYST values to the ignored root `.env`, using the names in
`.env.example`. Generate values locally with `secrets.token_urlsafe(32)`; do not
paste tokens into commands, screenshots, logs, or committed files. Then run:

```bash
make migrate
make mcp-bootstrap
make dev
make mcp-smoke
```

Bootstrap creates/resolves one user per persona and stores only SHA-256 token
hashes. Rerunning it rotates that user's credential to the supplied token.
The simulator's persona tokens are separate from MCP tokens. Keep the correct
GIGSIM_TOKEN_<PERSONA> values in `.env`. Persona corpora must already exist from
Step 0. The services never regenerate your corpus or seed/reset GigSim.

For host-only development use, for example:
`uv run uvicorn mcp_servers.portfolio.server:create_app --factory --port 8101 --no-access-log`.
Set MCP_BASE_URL to the matching host/port for each standalone server.

Schema snapshots: `make mcp-snapshot`; tests: `make test`. The opt-in
`tests/integration/test_mcp_postgres.py` suite uses FOUNDATION_TEST_DATABASE_URL,
creates/removes isolated simulator schemas, and intentionally retains test audit
rows/users in that disposable database. Migrate it before running. Set FOUNDATION_TEST_REDIS_URL to an isolated Redis
database (for example redis://localhost:6379/15) to run the shared-quota test.
Never run this
suite against a production database. It verifies concurrent submissions/messages,
Connects accounting, local holds, lost-response recovery, and immutable audit rows.

Only local drafts/holds and previews are usable before the later human approval
UI. Real proposal/message tools intentionally return `approval_required` without
a matching trusted database grant. There is no operator bypass command. Deferred
work: graph requeueing/degraded UI, retrieval experiments, the tool-design study,
and a grounded-agent demo. See `docs/TOOLS.md` and the Portfolio server README.

## Step 3: local RAG

Existing host Ollama is reused. The embedding model all-minilm:22m is added through
its API; Qwen stays qwen2.5:3b. The reranker uses CPU ONNX Runtime, not another
Ollama runtime or CUDA/PyTorch. Only selected pinned tokenizer/reranker files are
downloaded; setup checks free disk space. The existing compatible tokenizer cache
is reused when available. The model cache is about the size of the selected model
files, not an entire Hugging Face repository.

```bash
make rag-models
make rag-ingest
make dev
make mcp-smoke
make rag-eval
make rag-table
```

Model names/revisions and active variant are in agent/config.yaml. V0 remains the
development baseline until the user chooses after comparing all five. Switching
only active_variant needs no re-indexing; host tools read config directly, while
Compose needs `make dev` to rebuild the copied config. Never label an unmeasured
variant as the winner. No model downloads occur during service startup/tool calls.

`make rag-ingest` resolves provisioned users, indexes each assigned persona, and
prints embedded/reused/deleted counts. An unchanged second run should embed zero
chunks. Re-ingest after source edits/deletions. Missing models, missing/incompatible
indexes, or stale sources produce explicit tool errors; they do not trigger lexical
fallback. Rerun model setup after model/tokenizer revisions change, then re-ingest
if embeddings or chunk settings changed.

Portfolio containers mount data/personas and data/processed/rag read-only. Models,
Chroma data, and index manifests persist across container rebuilds. Host tools use
localhost:11434 / localhost:8001; Portfolio uses the existing host-gateway Ollama
bridge and internal Chroma service. Keep RAG_DATA_DIR consistent with the mounted
path when overriding it. Other MCP services need no RAG model/index access.

The read-only verify_claims tool expects chunk IDs returned by search, not full-item
IDs. It can exclude supported-looking sentences when numerical formats differ;
review the per-claim reason. A needs_attention report must not be treated as passed
verification. Approval grants/UI enforcement remains separate and unchanged.

## One RAG evaluation for Part B

Start the existing data services if needed:

```bash
docker compose --env-file .env -f infra/docker-compose.yml up -d postgres redis vector-store
```

Host Ollama needs the configured embedding/Qwen models. Provision MCP users and
matching indexes on a fresh installation with `make mcp-bootstrap` and
`make rag-ingest`. No running GigSim or MCP HTTP server is required for outcome
writes: the benchmark uses disposable in-process databases and real MCP sessions.

```bash
make rag-table       # offline: regenerate B5 CSV, report, and README
make rag-calibrate   # offline: import 30 human scores and regenerate reports
make rag-eval        # expensive: all five variants, verification, outcomes, ablation
make rag-smoke       # one-query/job, V0 check; never publishes as the full benchmark
```

For the corrected fixture, first run `make rag-repair-data` (already generated in
this workspace). It needs no models, raw-data download, or database writes. It
preserves original processed files, writes separate seed data under
`data/processed/repaired_clients/`, and creates `evals/datasets/rag_jobs_v2.json`.
Identical reruns are allowed; different existing output is not overwritten.
Future `make rag-eval` uses that v2 snapshot by default. Existing 200-token RAG
chunks remain compatible; no re-index is needed solely for the query-limit fix.

Each run performs embedding/context and positive/negative simulator preflight
checks before model inference. The runtime accepts 256 tokens, so query content
is capped at 254 plus two special tokens. Failed preflight stops the run rather
than burning hours on an incompatible benchmark. Preflight controls do not count
as measured replies. Full inference still takes hours on CPU; start it yourself.

`make eval` calls the same RAG evaluation. The exact eight-column B5 export is
`evals/results/rag_comparison.csv`. Its JSON also contains B3 before/after rates,
claim counts, MRR, retention, tokens, per-persona/category breakdowns, simulated
reply/hire rates, and ablation. The report includes all denominators and source
hashes. `make rag-table` neither reruns inference nor the completed R&D study.

New model runs create `evals/results/runs/<timestamp>/` and publish the active
CSV/JSON/Markdown to `evals/results/` only when the full benchmark completes.
Each stage flushes observations. Resume an interrupted run with:

```bash
uv run python -m evals.runners.rag_eval --resume evals/results/runs/<timestamp>
```

Resume rejects changed code/configuration/fixtures, models/runtime, and stage
index fingerprints. Completed stages and observations, including failed
observations, are retained. Controlled one-sentence claims are regression
fixtures; B3 and B5 claim rates come from generated drafts per variant. Smoke
runs require the same --limit/--variants options when resuming.

The active folder is recorded in `rag_comparison.json` as artifact_directory.
Fill only human_score in that folder's `rag_human_review.csv`, one integer 1–5
per row. `make rag-calibrate` validates all 30 items and reports exact agreement
and Cohen's kappa alongside judge means; low agreement does not hide scores.
The seeded review pack samples six scored outputs per variant, aiming for two
per persona and filling sparse cells within the same variant. Missing packs are
created offline when enough scored outputs exist; shortages are reported.
New runs receive new review packs; completed historical labels are not overwritten.

The original query and job measurements and human labels were imported once.
`evals/results/proposal/` and timestamped historical JSONL files remain source
evidence, not another active evaluation. Gold query labels remain provisional;
the human judge scores are a separate reviewed artifact. No shipped variant is
selected automatically. Hardware cost remains unknown, while paid API spend is zero.

## Separate R&D hypothesis analysis

The completed V2–V3 hypothesis study is retained. To analyze a historical run
explicitly, without model calls:

```bash
uv run python -m evals.runners.rag_rd_b --run evals/results/rag_20261113_155449.jsonl
```

Component ablation runs automatically at the end of `make rag-eval`; the existing
standalone ablation command remains available for focused research. It measures
full V3, without reranking, and without BM25, using embeddings and CPU reranking
only. It makes no Qwen calls and does not select a production variant.

## Using repaired seed files for later agent work

The evaluation uses disposable fixtures and does not update your live GigSim DB.
Fresh data generation (`make process`) now performs compatible client assignment
at the source. To seed a development simulator from the separately repaired files,
use explicit paths:

```bash
uv run python -m gigsim.seed --jobs data/processed/repaired_clients/jobs.json --stream data/processed/repaired_clients/stream_jobs.json --clients data/processed/repaired_clients/clients.json
```

This command merges repaired jobs/clients into the selected development database,
including revised client associations. It was not run during this repair.
No GigSim source or reply-rule changes were needed. The model smoke check was
kept under /tmp and did not replace the published historical comparison.
