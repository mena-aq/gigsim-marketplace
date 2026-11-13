.PHONY: install api test lint eval gigsim seed seed-reset download process personas personas-groq persona-prompts persona-import smoke

install:
	uv sync --extra dev

api:
	uv run uvicorn apps.api.main:app --reload --port 8000

gigsim:
	uv run uvicorn gigsim.main:app --reload --port 8081

seed:
	uv run python -m gigsim.seed

seed-reset:
	uv run python -m gigsim.seed --reset

download:
	uv run python data/scripts/download.py

process:
	uv run python data/scripts/process.py

personas:
	uv run python data/scripts/generate_personas.py

personas-groq:
	uv run python data/scripts/generate_personas.py --provider groq

persona-prompts:
	uv run python data/scripts/generate_personas.py --emit-prompts

persona-import:
	uv run python data/scripts/generate_personas.py --import-inbox

test:
	uv run pytest -q

lint:
	uv run ruff check .
	uv run ruff format --check --line-length 88 mcp_servers agent/mcp_client.py agent/marketplace_port.py tests/unit/test_mcp_layer.py tests/contract/test_mcp_schemas.py tests/integration/test_mcp_postgres.py scripts/mcp_smoke.py scripts/mcp_snapshot.py infra/ollama_bridge.py apps/api worker scripts/export_openapi.py tests/unit/test_api_health.py tests/integration/test_foundation_postgres.py

eval:
	uv run python -m evals.runners.run_demo_eval

smoke:
	./scripts/smoke_gigsim.sh

# Compose interpolation uses the root environment file explicitly.
COMPOSE = docker compose --env-file .env -f infra/docker-compose.yml

.PHONY: dev down migrate worker worker-smoke web-install web-check api-client

dev:
	$(COMPOSE) up --build -d

down:
	$(COMPOSE) down

migrate:
	uv run alembic upgrade head

worker:
	uv run arq worker.settings.WorkerSettings

worker-smoke:
	$(COMPOSE) exec api python -m worker.smoke

web-install:
	cd apps/web && npm ci

web-check:
	cd apps/web && npm run typecheck && npm run build

api-client:
	uv run python -m scripts.export_openapi
	cd apps/web && npm run api:generate

.PHONY: mcp-bootstrap mcp-smoke mcp-snapshot

mcp-bootstrap:
	uv run python -m mcp_servers.common.bootstrap

mcp-smoke:
	uv run python -m scripts.mcp_smoke

mcp-snapshot:
	uv run python -m scripts.mcp_snapshot
