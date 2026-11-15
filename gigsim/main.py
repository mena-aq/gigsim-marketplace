"""GigSim FastAPI application."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from gigsim.chaos import ChaosMiddleware
from gigsim.config import Settings
from gigsim.db import build_engine, build_sessionmaker, init_db
from gigsim.rate_limit import EXEMPT_PATHS, SlidingWindowLimiter, bearer_token_from_request
from gigsim.routers import admin, clients, connects, jobs, messages, proposals


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = build_engine(settings.database_url)
    sessionmaker = build_sessionmaker(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await init_db(app.state.engine)
        yield
        await app.state.engine.dispose()

    app = FastAPI(
        title="GigSim",
        description=(
            "Simulated freelance marketplace built for the GigBid project. "
            "Bearer-token auth per freelancer; admin token for stream/ground-truth endpoints."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = sessionmaker
    app.state.limiter = SlidingWindowLimiter(settings.rate_limit_per_minute)

    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        if request.url.path not in EXEMPT_PATHS:
            token = bearer_token_from_request(request)
            freelancer_id = None
            for fid, value in settings.freelancer_tokens.items():
                if token == value:
                    freelancer_id = fid
                    break
            if freelancer_id is not None:
                allowed, retry_after = app.state.limiter.check(freelancer_id)
                if not allowed:
                    return JSONResponse(
                        status_code=429,
                        content={"error": "rate_limited", "detail": "Too many requests"},
                        headers={"Retry-After": str(retry_after)},
                    )
        return await call_next(request)

    for router in (jobs.router, clients.router, proposals.router, messages.router, connects.router, admin.router):
        app.include_router(router)

    # Added last so chaos wraps everything (including the rate limiter) on the outside.
    app.add_middleware(ChaosMiddleware, settings=settings)

    @app.get("/health", tags=["meta"])
    async def health() -> dict:
        return {"status": "ok", "service": "gigsim"}

    return app


app = create_app()
