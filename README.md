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
RAG, graphs, the human approval UI, and full product screens remain future milestones. The shell reports actual readiness.

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
until the human approval UI exists. Marketplace integration is GigSim-only;
Upwork is excluded and GitHub is deferred by project choice.
