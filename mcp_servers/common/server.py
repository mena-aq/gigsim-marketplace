"""Authenticated Streamable HTTP factory and minimal ASGI health endpoint."""

import re
from contextlib import asynccontextmanager

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse
from starlette.routing import Route

from mcp_servers.common.security import (
    TRACE_ID,
    DatabaseTokenVerifier,
    install_log_redaction,
)


class TraceMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        headers = dict(scope.get("headers", []))
        trace = headers.get(b"x-trace-id", b"").decode("ascii", errors="ignore")
        token = TRACE_ID.set(
            trace if re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", trace) else None
        )
        try:
            await self.app(scope, receive, send)
        finally:
            TRACE_ID.reset(token)


def make_server(name, runtime):
    @asynccontextmanager
    async def lifespan(server):
        yield runtime

    return FastMCP(
        name,
        lifespan=lifespan,
        stateless_http=True,
        json_response=True,
        token_verifier=DatabaseTokenVerifier(
            runtime.sessions, runtime.settings.mcp_base_url + "/mcp"
        ),
        auth=AuthSettings(
            issuer_url=runtime.settings.mcp_base_url,
            resource_server_url=runtime.settings.mcp_base_url + "/mcp",
            required_scopes=["gigbid"],
            validate_token_resource=True,
        ),
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[
                "localhost:*",
                "127.0.0.1:*",
                "portfolio-mcp:*",
                "marketplace-mcp:*",
                "workspace-mcp:*",
            ],
            allowed_origins=["http://localhost:*", "http://127.0.0.1:*"],
        ),
    )


def http_app(server, runtime):
    install_log_redaction()
    app = server.streamable_http_app()
    previous_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        try:
            async with previous_lifespan(app):
                yield
        finally:
            await runtime.close()

    async def health(request):
        return JSONResponse({"status": "ok", "service": server.name})

    app.router.lifespan_context = lifespan
    app.routes.append(Route("/health", health))
    app.add_middleware(TraceMiddleware)
    return app
