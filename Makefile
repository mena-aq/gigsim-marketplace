.PHONY: install api test lint eval gigsim seed seed-demo-chats match-jobs seed-reset download process personas personas-groq persona-prompts persona-import smoke

install:
	uv sync --extra dev

api:
	uv run uvicorn apps.api.main:app --reload --port 8000

gigsim:
	uv run uvicorn gigsim.main:app --reload --port 8081

seed:
	uv run python -m gigsim.seed

seed-demo-chats:
	uv run python -m scripts.seed_demo_chats

match-jobs:
	uv run python -m scripts.match_jobs

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
	uv run ruff format --check --line-length 88 agent apps/api/orchestration.py scripts/render_graphs.py tests/unit/test_graphs.py tests/unit/test_node_model.py tests/unit/test_graph_connects.py tests/unit/test_graph_runtime_failures.py tests/integration/test_graph_postgres.py
	uv run ruff format --check --line-length 88 rag tests/unit/test_rag.py tests/unit/rag_fakes.py evals/runners/rag_eval.py evals/runners/rag_table.py evals/runners/rag_environment.py evals/runners/rag_study.py evals/runners/rag_rd_b.py evals/runners/rag_ablation.py evals/runners/tool_eval.py tests/unit/test_rag_studies.py evals/runners/rag_metrics.py evals/runners/rag_retrieval.py evals/runners/rag_workflow.py evals/runners/rag_outcomes.py evals/runners/rag_calibration.py evals/runners/rag_preflight.py evals/runners/rag_diagnostics.py tests/unit/test_rag_evaluation.py tests/unit/test_agent_compare.py evals/runners/agent_compare.py evals/runners/agent_compare_metrics.py agent/baselines tests/unit/test_rag_unified.py tests/unit/test_rag_repairs.py data/client_matching.py data/scripts/repair_client_assignments.py mcp_servers agent/mcp_client.py agent/marketplace_port.py tests/unit/test_mcp_layer.py tests/contract/test_mcp_schemas.py tests/integration/test_mcp_postgres.py scripts/mcp_smoke.py scripts/mcp_snapshot.py infra/ollama_bridge.py apps/api worker scripts/export_openapi.py tests/unit/test_api_health.py tests/integration/test_foundation_postgres.py

eval:
	$(MAKE) rag-eval

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
	uv run python -m agent.persistence

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

.PHONY: rag-models rag-ingest rag-eval rag-table agent-compare

rag-models:
	uv run python -m rag.models

rag-ingest:
	uv run python -m rag.ingest.pipeline

rag-eval:
	uv run python -m evals.runners.rag_eval

# R&D question C (reduced): single agent vs graph. ARGS="--limit 2" for a smoke run,
# ARGS="--resume evals/results/agent_compare/<run>" to continue.
agent-compare:
	uv run python -m evals.runners.agent_compare $(ARGS)

rag-table:
	uv run python -m evals.runners.rag_table --update-readme


.PHONY: rag-calibrate rag-smoke rag-repair-data

rag-calibrate:
	uv run python -m evals.runners.rag_table --calibrate --update-readme

rag-smoke:
	uv run python -m evals.runners.rag_eval --limit 1 --variants v0

rag-repair-data:
	uv run python -m data.scripts.repair_client_assignments

.PHONY: tool-eval

tool-eval:
	uv run python -m evals.runners.tool_eval

.PHONY: graph-diagrams graph-test

graph-diagrams:
	uv run python -m scripts.render_graphs

graph-test:
	uv run pytest -q tests/unit/test_graphs.py tests/integration/test_graph_postgres.py
