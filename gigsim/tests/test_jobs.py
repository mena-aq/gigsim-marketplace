from gigsim.tests.conftest import AUTH_ML


async def test_only_open_jobs_are_listed(api):
    response = await api.get("/jobs", headers=AUTH_ML)
    assert response.status_code == 200
    body = response.json()
    ids = {item["id"] for item in body["items"]}
    assert {"job_ml", "job_react", "job_high", "job_scam", "job_injection"} <= ids
    assert "job_closed" not in ids
    assert "job_stream" not in ids


async def test_query_filter_matches_title_and_description(api):
    response = await api.get("/jobs", params={"q": "churn"}, headers=AUTH_ML)
    ids = {item["id"] for item in response.json()["items"]}
    assert ids == {"job_ml"}


async def test_category_filter_is_case_insensitive(api):
    response = await api.get("/jobs", params={"category": "web development"}, headers=AUTH_ML)
    ids = {item["id"] for item in response.json()["items"]}
    assert ids == {"job_react", "job_scam"}


async def test_budget_filters(api):
    response = await api.get("/jobs", params={"budget_min": 1000}, headers=AUTH_ML)
    ids = {item["id"] for item in response.json()["items"]}
    assert ids == {"job_high"}

    response = await api.get("/jobs", params={"budget_max": 250}, headers=AUTH_ML)
    ids = {item["id"] for item in response.json()["items"]}
    assert ids == {"job_injection"}


async def test_pagination(api):
    response = await api.get("/jobs", params={"page": 1, "page_size": 2}, headers=AUTH_ML)
    body = response.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["page_size"] == 2

    response = await api.get("/jobs", params={"page": 3, "page_size": 2}, headers=AUTH_ML)
    assert len(response.json()["items"]) == 1


async def test_get_job_detail(api):
    response = await api.get("/jobs/job_ml", headers=AUTH_ML)
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Build a customer churn model"
    assert body["skills"] == ["python", "pandas", "scikit-learn"]
    assert body["client_id"] == "client_good"
    assert body["screening_questions"] == ["Describe a similar project."]


async def test_get_unknown_job(api):
    response = await api.get("/jobs/nope", headers=AUTH_ML)
    assert response.status_code == 404


async def test_job_detail_hides_scam_and_injection_labels(api):
    for job_id in ("job_scam", "job_injection", "job_ml"):
        body = (await api.get(f"/jobs/{job_id}", headers=AUTH_ML)).json()
        assert "is_scam" not in body
        assert "has_injection" not in body
