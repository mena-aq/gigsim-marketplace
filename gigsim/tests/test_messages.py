from gigsim import reply_sim
from gigsim.tests.conftest import AUTH_FULLSTACK, AUTH_ML, drain


class ScriptedRng:
    def __init__(self, outcome=None, roll=0.0):
        self.outcome = outcome
        self.roll = roll

    def choices(self, population, weights=None):
        return [self.outcome]

    def random(self):
        return self.roll


async def submit(api, job_id="job_ml", key="msg-1"):
    return await api.post(
        "/proposals",
        json={
            "job_id": job_id,
            "cover_letter": "I have shipped churn models with python.",
            "skills_mentioned": ["python"],
            "idempotency_key": key,
        },
        headers=AUTH_ML,
    )


async def test_freelancer_can_reply_in_conversation(api_factory, monkeypatch):
    api = await api_factory(reply_delay_min_seconds=0.0, reply_delay_max_seconds=0.0)
    monkeypatch.setattr(reply_sim, "rng", ScriptedRng(outcome="replied"))
    await submit(api)
    await drain()

    response = await api.post(
        "/messages",
        json={"conversation_id": "job_ml:ml_engineer", "body": "Happy to walk you through it."},
        headers=AUTH_ML,
    )
    assert response.status_code == 201
    assert response.json()["sender"] == "freelancer"

    messages = (
        await api.get("/messages", params={"conversation_id": "job_ml:ml_engineer"}, headers=AUTH_ML)
    ).json()
    assert [m["sender"] for m in messages] == ["client", "freelancer"]


async def test_conversation_summaries(api_factory, monkeypatch):
    api = await api_factory(reply_delay_min_seconds=0.0, reply_delay_max_seconds=0.0)
    monkeypatch.setattr(reply_sim, "rng", ScriptedRng(outcome="replied"))
    await submit(api)
    await drain()

    summaries = (await api.get("/messages/conversations", headers=AUTH_ML)).json()
    assert len(summaries) == 1
    assert summaries[0]["conversation_id"] == "job_ml:ml_engineer"
    assert summaries[0]["proposal_status"] == "replied"
    assert summaries[0]["message_count"] == 1
    assert summaries[0]["last_message"] is not None


async def test_other_freelancer_cannot_access_conversation(api):
    await submit(api, key="own-1")
    response = await api.get(
        "/messages", params={"conversation_id": "job_ml:ml_engineer"}, headers=AUTH_FULLSTACK
    )
    assert response.status_code == 403
    response = await api.post(
        "/messages",
        json={"conversation_id": "job_ml:ml_engineer", "body": "hijack"},
        headers=AUTH_FULLSTACK,
    )
    assert response.status_code == 403


async def test_unknown_or_foreign_conversation(api):
    response = await api.get(
        "/messages", params={"conversation_id": "job_ml:nope"}, headers=AUTH_ML
    )
    assert response.status_code == 403
    response = await api.post(
        "/messages",
        json={"conversation_id": "nothing:ml_engineer", "body": "hello"},
        headers=AUTH_ML,
    )
    assert response.status_code == 404


async def test_message_dry_run_is_not_persisted(api):
    await submit(api, key="drymsg-1")
    response = await api.post(
        "/messages",
        json={"conversation_id": "job_ml:ml_engineer", "body": "draft only", "dry_run": True},
        headers=AUTH_ML,
    )
    assert response.status_code == 201
    messages = (
        await api.get("/messages", params={"conversation_id": "job_ml:ml_engineer"}, headers=AUTH_ML)
    ).json()
    assert messages == []
