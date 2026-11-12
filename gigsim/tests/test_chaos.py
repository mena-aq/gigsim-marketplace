from gigsim.tests.conftest import AUTH_ML


async def test_chaos_fails_requests_when_enabled_at_full_rate(api_factory):
    api = await api_factory(chaos_enabled=True, chaos_error_rate=1.0)
    response = await api.get("/jobs", headers=AUTH_ML)
    assert response.status_code == 500
    assert response.json()["error"] == "gigsim_chaos"


async def test_chaos_never_breaks_health_checks(api_factory):
    api = await api_factory(chaos_enabled=True, chaos_error_rate=1.0)
    response = await api.get("/health")
    assert response.status_code == 200


async def test_chaos_disabled_by_error_rate_zero(api_factory):
    api = await api_factory(chaos_enabled=True, chaos_error_rate=0.0)
    assert (await api.get("/jobs", headers=AUTH_ML)).status_code == 200


async def test_chaos_off_by_default_in_tests(api):
    assert (await api.get("/jobs", headers=AUTH_ML)).status_code == 200
