from gigsim.tests.conftest import AUTH_ML


async def test_requests_above_the_limit_get_429_with_retry_after(api_factory):
    api = await api_factory(rate_limit_per_minute=3)
    for _ in range(3):
        response = await api.get("/connects", headers=AUTH_ML)
        assert response.status_code == 200
    response = await api.get("/connects", headers=AUTH_ML)
    assert response.status_code == 429
    assert response.json()["error"] == "rate_limited"
    retry_after = response.headers.get("Retry-After")
    assert retry_after is not None and int(retry_after) >= 1


async def test_health_is_not_rate_limited(api_factory):
    api = await api_factory(rate_limit_per_minute=2)
    for _ in range(2):
        assert (await api.get("/connects", headers=AUTH_ML)).status_code == 200
    assert (await api.get("/health")).status_code == 200
    assert (await api.get("/connects", headers=AUTH_ML)).status_code == 429


async def test_unauthenticated_requests_are_not_counted(api_factory):
    api = await api_factory(rate_limit_per_minute=2)
    for _ in range(5):
        assert (await api.get("/jobs")).status_code == 401


async def test_admin_requests_are_not_counted(api_factory):
    api = await api_factory(rate_limit_per_minute=2)
    admin = {"Authorization": "Bearer test-admin"}
    for _ in range(5):
        assert (await api.get("/admin/stats", headers=admin)).status_code == 200


async def test_rate_limits_are_per_freelancer(api_factory):
    api = await api_factory(rate_limit_per_minute=2)
    other = {"Authorization": "Bearer test-token-fullstack"}
    for _ in range(2):
        assert (await api.get("/connects", headers=AUTH_ML)).status_code == 200
    assert (await api.get("/connects", headers=AUTH_ML)).status_code == 429
    assert (await api.get("/connects", headers=other)).status_code == 200
