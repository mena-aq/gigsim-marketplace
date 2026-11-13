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
