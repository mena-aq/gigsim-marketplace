FROM ghcr.io/astral-sh/uv:0.12.15 AS uv
FROM python:3.12-slim
COPY --from=uv /uv /uvx /bin/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
COPY apps/ apps/
COPY worker/ worker/
COPY alembic.ini ./
COPY infra/ollama_bridge.py infra/ollama_bridge.py
ENV PATH="/app/.venv/bin:$PATH"
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
