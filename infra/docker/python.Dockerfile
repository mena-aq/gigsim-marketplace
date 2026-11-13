FROM ghcr.io/astral-sh/uv:0.12.15 AS uv
FROM python:3.12-slim
COPY --from=uv /uv /uvx /bin/
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 libgomp1 && rm -rf /var/lib/apt/lists/*
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
COPY apps/ apps/
COPY worker/ worker/
COPY agent/ agent/
COPY rag/ rag/
COPY mcp_servers/ mcp_servers/
COPY alembic.ini ./
COPY infra/ollama_bridge.py infra/ollama_bridge.py
ENV PATH="/app/.venv/bin:$PATH"
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
