"""Public infrastructure endpoints. Business routes require future authentication."""

import asyncio
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from apps.api.config import Settings
from apps.api.db import build_engine
from apps.api.orchestration import router as orchestration_router
from mcp_servers.common.security import install_log_redaction


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["gigbid-api"] = "gigbid-api"


class ReadyResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    postgres: Literal["ok", "unavailable"]
    redis: Literal["ok", "unavailable"]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        install_log_redaction()
        app.state.settings = settings
        app.state.engine = build_engine(settings.database_url)
        app.state.redis = Redis.from_url(
            settings.redis_url, socket_connect_timeout=2, socket_timeout=2
        )
        try:
            yield
        finally:
            await app.state.redis.aclose()
            await app.state.engine.dispose()

    app = FastAPI(title="GigBid API", version="0.1.0", lifespan=lifespan)
    app.include_router(orchestration_router)

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse()

    async def check_postgres() -> str:
        try:
            async with asyncio.timeout(3):
                async with app.state.engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
            return "ok"
        except (SQLAlchemyError, OSError, TimeoutError):
            return "unavailable"

    async def check_redis() -> str:
        try:
            async with asyncio.timeout(3):
                await app.state.redis.ping()
            return "ok"
        except (RedisError, OSError, TimeoutError):
            return "unavailable"

    @app.get(
        "/ready",
        response_model=ReadyResponse,
        responses={503: {"model": ReadyResponse}},
    )
    async def ready() -> JSONResponse:
        postgres, redis = await asyncio.gather(check_postgres(), check_redis())
        result = ReadyResponse(
            status="ok" if postgres == redis == "ok" else "unavailable",
            postgres=postgres,
            redis=redis,
        )
        return JSONResponse(
            result.model_dump(), status_code=200 if result.status == "ok" else 503
        )

    return app


app = create_app()
