"""Readiness must distinguish dependency outages without leaking connection details."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from apps.api.config import Settings
from apps.api.main import create_app


@pytest.mark.parametrize(
    "postgres_ok,redis_ok", [(True, True), (False, True), (True, False), (False, False)]
)
def test_readiness(postgres_ok, redis_ok, monkeypatch):
    app = create_app(Settings(database_url="sqlite+aiosqlite://", _env_file=None))
    with TestClient(app) as client:
        connection = AsyncMock()
        manager = MagicMock()
        manager.__aenter__ = AsyncMock(return_value=connection)
        manager.__aexit__ = AsyncMock(return_value=False)
        if not postgres_ok:
            manager.__aenter__.side_effect = ConnectionError(
                "private connection details"
            )
        monkeypatch.setattr(type(app.state.engine), "connect", lambda self: manager)
        app.state.redis.ping = AsyncMock(return_value=True)
        if not redis_ok:
            app.state.redis.ping.side_effect = ConnectionError("private credentials")
        assert client.get("/health").status_code == 200
        response = client.get("/ready")
        assert response.status_code == (200 if postgres_ok and redis_ok else 503)
        assert response.json() == {
            "status": "ok" if postgres_ok and redis_ok else "unavailable",
            "postgres": "ok" if postgres_ok else "unavailable",
            "redis": "ok" if redis_ok else "unavailable",
        }
