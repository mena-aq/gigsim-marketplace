from gigsim.tests.conftest import AUTH_ML


async def test_unknown_client_returns_404(api):
    response = await api.get("/clients/nope/history", headers=AUTH_ML)
    assert response.status_code == 404


async def test_client_history_lists_past_proposals(api):
    await api.post(
        "/proposals",
        json={
            "job_id": "job_ml",
            "cover_letter": "I have shipped churn models with python.",
            "skills_mentioned": ["python"],
            "idempotency_key": "hist-1",
        },
        headers=AUTH_ML,
    )
    response = await api.get("/clients/client_good/history", headers=AUTH_ML)
    assert response.status_code == 200
    body = response.json()
    assert body["client"]["name"] == "Northwind Labs"
    assert body["client"]["payment_verified"] is True
    assert body["proposals_received"] == 1
    assert body["past_proposals"][0]["job_id"] == "job_ml"
    assert body["past_proposals"][0]["status"] == "submitted"
    assert body["reviews"] == ["Clear requirements and fast payments."]


async def test_client_history_hides_hidden_preferences(api):
    body = (await api.get("/clients/client_good/history", headers=AUTH_ML)).json()
    assert "hidden_preferences" not in body
    assert "hidden_preferences" not in body["client"]
    assert "must_have_skills" not in body


async def test_client_with_no_proposals(api):
    body = (await api.get("/clients/client_react/history", headers=AUTH_ML)).json()
    assert body["proposals_received"] == 0
    assert body["past_proposals"] == []
