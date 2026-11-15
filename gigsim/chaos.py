"""Chaos middleware: fails a random fraction of requests with HTTP 500.

This deliberately lets GigBid exercise its retry and degraded-mode logic.
Disable with GIGSIM_CHAOS_ENABLED=false (tests always run with it off).
"""

import random

from gigsim.rate_limit import EXEMPT_PATHS


class ChaosMiddleware:
    def __init__(self, app, settings):
        self.app = app
        self.enabled = settings.chaos_enabled
        self.error_rate = settings.chaos_error_rate
        self.rng = random.Random(settings.chaos_seed)

    async def __call__(self, scope, receive, send):
        if (
            self.enabled
            and scope["type"] == "http"
            and scope.get("path") not in EXEMPT_PATHS
            and self.rng.random() < self.error_rate
        ):
            await self._send_500(scope, receive, send)
            return
        await self.app(scope, receive, send)

    @staticmethod
    async def _send_500(scope, receive, send) -> None:
        body = b'{"error": "gigsim_chaos", "detail": "simulated transient failure"}'
        await send({
            "type": "http.response.start",
            "status": 500,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        })
        await send({"type": "http.response.body", "body": body})
