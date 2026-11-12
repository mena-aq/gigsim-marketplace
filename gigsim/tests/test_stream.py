from gigsim.tests.conftest import AUTH_ADMIN, AUTH_ML


async def test_admin_stream_requires_admin_token(api):
    assert (await api.post("/admin/stream")).status_code == 401
    assert (await api.post("/admin/stream", headers=AUTH_ML)).status_code == 401


async def test_admin_stream_releases_pending_jobs(api):
    assert (await api.get("/jobs", headers=AUTH_ML)).json()["total"] == 5

    response = await api.post("/admin/stream", params={"count": 1}, headers=AUTH_ADMIN)
    assert response.status_code == 200
    body = response.json()
    assert body["released"] == ["job_stream"]
    assert body["remaining"] == 0

    listed = (await api.get("/jobs", headers=AUTH_ML)).json()
    assert listed["total"] == 6
    assert "job_stream" in {item["id"] for item in listed["items"]}


async def test_admin_stream_when_nothing_pending(api):
    await api.post("/admin/stream", params={"count": 5}, headers=AUTH_ADMIN)
    response = await api.post("/admin/stream", params={"count": 5}, headers=AUTH_ADMIN)
    assert response.json() == {"released": [], "remaining": 0}


async def test_admin_stream_rejects_bad_count(api):
    response = await api.post("/admin/stream", params={"count": 0}, headers=AUTH_ADMIN)
    assert response.status_code == 422


async def test_admin_ground_truth_exposes_labels(api):
    response = await api.get("/admin/jobs/job_scam", headers=AUTH_ADMIN)
    assert response.status_code == 200
    assert response.json()["is_scam"] is True

    response = await api.get("/admin/jobs/job_injection", headers=AUTH_ADMIN)
    assert response.json()["has_injection"] is True

    response = await api.get("/admin/jobs/job_ml", headers=AUTH_ADMIN)
    body = response.json()
    assert body["is_scam"] is False
    assert body["has_injection"] is False


async def test_admin_stats(api):
    body = (await api.get("/admin/stats", headers=AUTH_ADMIN)).json()
    assert body["jobs_total"] == 7
    assert body["jobs_open"] == 5
    assert body["jobs_pending"] == 1
    assert body["jobs_filled"] == 1
    assert body["scams"] == 1
    assert body["injections"] == 1
    assert body["clients"] == 3
