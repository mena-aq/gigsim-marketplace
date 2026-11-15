from sqlalchemy import select

from gigsim.models import AuditLog, Connects
from gigsim.tests.conftest import AUTH_ML


def proposal_payload(job_id="job_ml", **overrides) -> dict:
    payload = {
        "job_id": job_id,
        "cover_letter": "I have shipped several churn models with python and pandas.",
        "skills_mentioned": ["python", "pandas"],
        "idempotency_key": "key-001",
    }
    payload.update(overrides)
    return payload


async def test_submit_proposal_deducts_connects(api):
    before = (await api.get("/connects", headers=AUTH_ML)).json()["balance"]
    response = await api.post("/proposals", json=proposal_payload(), headers=AUTH_ML)
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "submitted"
    assert body["connects_spent"] == 8
    assert body["conversation_id"] == "job_ml:ml_engineer"
    after = (await api.get("/connects", headers=AUTH_ML)).json()["balance"]
    assert after == before - 8


async def test_high_budget_job_costs_more_connects(api):
    response = await api.post("/proposals", json=proposal_payload("job_high"), headers=AUTH_ML)
    assert response.status_code == 201
    assert response.json()["connects_spent"] == 16


async def test_idempotency_key_returns_original_result(api):
    first = await api.post(
        "/proposals", json=proposal_payload(idempotency_key="idem-1"), headers=AUTH_ML
    )
    balance_after_first = (await api.get("/connects", headers=AUTH_ML)).json()["balance"]
    second = await api.post(
        "/proposals", json=proposal_payload(idempotency_key="idem-1"), headers=AUTH_ML
    )
    assert second.status_code == 201
    assert second.json()["idempotent_replay"] is True
    assert second.json()["id"] == first.json()["id"]
    assert (await api.get("/connects", headers=AUTH_ML)).json()["balance"] == balance_after_first


async def test_dry_run_persists_nothing(api):
    response = await api.post(
        "/proposals", json=proposal_payload(idempotency_key="dry-1", dry_run=True), headers=AUTH_ML
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "dry_run"
    assert body["connects_remaining"] == 60 - 8
    assert (await api.get("/proposals", headers=AUTH_ML)).json() == []
    assert (await api.get("/connects", headers=AUTH_ML)).json()["balance"] == 60


async def test_insufficient_connects_rejected(api):
    await api.post("/proposals", json=proposal_payload(idempotency_key="warm-1"), headers=AUTH_ML)
    async with api.app.state.sessionmaker() as session:
        connects = await session.get(Connects, "ml_engineer")
        connects.balance = 3
        await session.commit()
    response = await api.post(
        "/proposals", json=proposal_payload(idempotency_key="poor-1"), headers=AUTH_ML
    )
    assert response.status_code == 402
    assert response.json()["detail"]["error"] == "insufficient_connects"


async def test_closed_job_rejects_proposals(api):
    response = await api.post("/proposals", json=proposal_payload("job_closed"), headers=AUTH_ML)
    assert response.status_code == 409


async def test_unknown_job_rejects_proposals(api):
    response = await api.post("/proposals", json=proposal_payload("nope"), headers=AUTH_ML)
    assert response.status_code == 404


async def test_skills_mentioned_falls_back_to_job_skills(api):
    response = await api.post(
        "/proposals",
        json=proposal_payload(
            idempotency_key="skills-1", skills_mentioned=[], cover_letter="python and pandas expert"
        ),
        headers=AUTH_ML,
    )
    assert response.status_code == 201
    assert set(response.json()["skills_mentioned"]) == {"python", "pandas"}


async def test_submission_is_audited(api):
    await api.post("/proposals", json=proposal_payload(idempotency_key="audit-1"), headers=AUTH_ML)
    async with api.app.state.sessionmaker() as session:
        rows = (
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.action == "proposal_submitted")
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].payload["job_id"] == "job_ml"
