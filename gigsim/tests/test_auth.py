from gigsim.tests.conftest import AUTH_ADMIN, AUTH_FULLSTACK, AUTH_ML


async def test_missing_token_is_rejected(api):
    response = await api.get("/jobs")
    assert response.status_code == 401


async def test_invalid_token_is_rejected(api):
    response = await api.get("/jobs", headers={"Authorization": "Bearer wrong-token"})
    assert response.status_code == 401


async def test_valid_token_is_accepted(api):
    response = await api.get("/connects", headers=AUTH_ML)
    assert response.status_code == 200
    assert response.json()["freelancer_id"] == "ml_engineer"


async def test_each_persona_token_maps_to_its_own_freelancer(api):
    response = await api.get("/connects", headers=AUTH_FULLSTACK)
    assert response.status_code == 200
    assert response.json()["freelancer_id"] == "fullstack_dev"


async def test_admin_endpoints_reject_freelancer_tokens(api):
    response = await api.post("/admin/stream", headers=AUTH_ML)
    assert response.status_code == 401


async def test_admin_token_accepted(api):
    response = await api.get("/admin/stats", headers=AUTH_ADMIN)
    assert response.status_code == 200


async def test_health_is_public(api):
    response = await api.get("/health")
    assert response.status_code == 200
    assert response.json()["service"] == "gigsim"
