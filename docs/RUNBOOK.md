# Local foundation runbook

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

## Reading and reproducing the RAG comparison

The checked-in development labels are agent-authored and await human review:
`evals/datasets/rag_dev.json` and `claim_dev.json`. They are not an instructor gold
set, hidden test set, or human judge calibration. Review/relabel them before making
strong quality claims. See docs/RAG_EXPERIMENT.md for the comparison protocol.

`make rag-eval` runs real local models sequentially, flushing each observation to a
new timestamped JSONL file. It writes rag_comparison.json plus generated CSV and
Markdown only after the complete run. To resume an interrupted matching run:

```bash
uv run python -m evals.runners.rag_eval --resume evals/results/<run>.jsonl
```

Resume refuses changed retrieval/prompt code, configuration, indexes, datasets,
and recorded model/runtime versions. Derived quality metrics are recomputed from
the stored rankings; completed model calls are not repeated. Quality aggregates
count retrieval failures as failures, not successful no-evidence refusals. The
comparison includes positive-query Recall@5, MRR, nDCG@10, negative-query correct
abstention, per-persona/query-type breakdowns, p50/p95 latency, and reported model
usage. V8 grades five candidates and may return fewer than ten supported items.
Each run also has an environment sidecar recording actual Ollama model digests,
server/library versions, and the dependency-lock hash. Verification metrics use
one-sentence examples with supplied evidence; they do not measure full proposal
claim accuracy. Local hardware cost is unknown; no paid API is called. Proposal outcomes and
calibrated-judge metrics remain deferred. The user selects the variant explicitly.

CI correctness tests use declared deterministic model substitutes and isolated
indexes; they do not download weights or publish fake benchmark scores. Actual
model smoke checks and comparisons are separate from the test suite.
