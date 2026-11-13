# GigBid API foundation

`make api` serves FastAPI on port 8000. `GET /health` checks liveness;
`GET /ready` checks Postgres and Redis, returning 503 if either is unavailable.
Both have typed response contracts. No business data is publicly exposed.

Configuration reads the root `.env`. GigBid uses its own async SQLAlchemy engine,
models, and Alembic migrations. Run `make migrate` before startup; do not import
GigSim's database helpers. See `docs/RUNBOOK.md` for setup and checks.
