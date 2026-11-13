# GigSim — Simulated Freelance Marketplace

GigSim is a stand-in for a real freelance marketplace API (e.g. Upwork). The GigBid
agent talks to it through the marketplace port; GigSim stores jobs, clients,
proposals, connects and message threads, simulates client replies, rate limits and
occasional failures. Built in Phase 0 — see `AGENT.md` (section 0e) for the spec.

## Quickstart

```bash
# 1. Postgres for GigSim (host port 5433)
docker compose -f infra/docker-compose.yml up -d gigsim-postgres

# 2. Generate data (or use data/processed/*.json if already built)
make download && make process

# 3. Seed the database
make seed

# 4. Run the API on :8081
make gigsim
# or: .venv/bin/python -m uvicorn gigsim.main:app --port 8081
```

Interactive docs at `http://localhost:8081/docs`. Health check: `GET /health`.

## Authentication

All freelancer/user endpoints require a bearer token. Each token maps to one of
three seeded personas:

| Token (env var) | Default | Persona |
| --- | --- | --- |
| `GIGSIM_TOKEN_ML_ENGINEER` | `test-token-ml-engineer` | ml_engineer |
| `GIGSIM_TOKEN_FULLSTACK_DEV` | `test-token-fullstack-dev` | fullstack_dev |
| `GIGSIM_TOKEN_DATA_ANALYST` | `test-token-data-analyst` | data_analyst |
| `GIGSIM_ADMIN_TOKEN` | `gigsim-admin-token` | admin (ground truth + stream) |

```bash
curl -H "Authorization: Bearer test-token-ml-engineer" http://localhost:8081/jobs
```

## Endpoints

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/health` | unauthenticated |
| GET | `/jobs` | search: `q`, `category`, `budget_min`, `budget_max`, `page` |
| GET | `/jobs/{id}` | one job |
| GET | `/clients/{id}/history` | spend, hire rate, reviews |
| GET | `/connects` | balance for the authenticated freelancer |
| GET | `/messages` | thread for `?conversation_id=` |
| GET | `/messages/conversations` | conversation summaries for the freelancer |
| GET | `/proposals` | the freelancer's proposals (extension) |
| POST | `/proposals` | submit; deduped by `idempotency_key`; `dry_run=true` supported |
| POST | `/messages` | send a message in an existing conversation |
| POST | `/admin/stream?count=N` | release N pending stream jobs (admin) |
| GET | `/admin/jobs/{id}` | ground truth: `is_scam`, `has_injection` (admin) |
| GET | `/admin/stats` | dataset counters (incl. `bad_actors`) (admin) |

`is_scam` / `has_injection` are **never** exposed on public endpoints — the agent
must detect them itself. Ground truth is only readable via the admin endpoints
(for evaluation).

## Behaviour rules

- **Rate limit**: 60 requests/min per freelancer (sliding window). Exceeding it
  returns `429` with a `Retry-After` header. `/health`, `/`, `/docs`, `/openapi.json`
  and `/redoc` are exempt.
- **Chaos**: when `GIGSIM_CHAOS_ENABLED=true` (default), ~5% of requests fail with
  a simulated `500` (same exempt paths). The agent must retry with backoff.
- **Connects**: initial balance 60. Submitting a proposal costs 8 connects for
  budgets under $1000, 16 otherwise. Dry runs are free.
- **Reply simulation**: after a proposal, a simulated client replies after a
  5–30s delay (`GIGSIM_REPLY_DELAY_*`). Outcomes follow the rule engine in
  `gigsim/reply_sim.py`: clients with hire rate < 0.1 never reply; proposals that
  do not mention the client's must-have skills never get a reply; "Dear Hiring
  Manager" openers never get a reply; otherwise `no_reply`/`replied`/`interview`
  are sampled, and interviews convert to `hired` (job becomes `filled`) ~30% of
  the time.
- **Conversations**: `conversation_id` = `{job_id}:{freelancer_id}`.
- **Stream jobs**: seeded with status `pending`; released to `open` via
  `POST /admin/stream`.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `GIGSIM_DATABASE_URL` | `sqlite+aiosqlite:///./gigsim.db` | database (`infra/.env` uses Postgres) |
| `GIGSIM_INITIAL_CONNECTS` | `60` | starting connects per freelancer |
| `GIGSIM_REPLY_DELAY_MIN_SECONDS` / `_MAX_` | `5` / `30` | client reply delay |
| `GIGSIM_RATE_LIMIT_PER_MINUTE` | `60` | requests/min per freelancer |
| `GIGSIM_CHAOS_ENABLED` | `true` | random 500s |
| `GIGSIM_CHAOS_ERROR_RATE` | `0.05` | chaos probability |
| `GIGSIM_ADMIN_TOKEN` | `gigsim-admin-token` | admin bearer token |

## Testing

```bash
.venv/bin/python -m pytest gigsim/tests -q   # 60 tests, no external services
```

Tests run against an in-memory SQLite database with reply scheduling disabled,
so they are fast, deterministic and need no Postgres.

For an end-to-end check against a running, seeded server:

```bash
make smoke                    # health, search, history, connects, dry-run, admin stats
SMOKE_SUBMIT=1 make smoke     # also submits a proposal and checks idempotent replay
SMOKE_SUBMIT=1 SMOKE_WAIT_REPLY=1 make smoke   # also waits for the simulated reply
```

Set `GIGSIM_CHAOS_ENABLED=false` while running the smoke test to avoid random 500s.

## Docker

```bash
docker compose -f infra/docker-compose.yml up -d gigsim-postgres gigsim
```

The `gigsim` container runs the API on port 8081 and mounts
`../data/processed` read-only for seeding at startup.

## Step 2 write-safety update

Message requests optionally accept `idempotency_key` (required by the MCP layer).
Same-key retries return the stored response; changed payloads return 409. Proposal
writes now have the same payload-conflict protection and immutable receipts.
Postgres serializes writes per freelancer to prevent concurrent double spending.
The additive `write_receipts` table is created by normal simulator startup; no
existing tables or data are reset. SQLite uses an in-process lock for tests;
multi-process write-safety is verified against Postgres.
