from gigsim import reply_sim
from gigsim.tests.conftest import AUTH_ML, drain


class ScriptedRng:
    def __init__(self, outcome=None, roll=0.0):
        self.outcome = outcome
        self.roll = roll

    def choices(self, population, weights=None):
        return [self.outcome]

    def random(self):
        return self.roll


GOOD_PREFS = {"must_have_skills": ["python"]}


def test_low_hire_rate_clients_never_reply(monkeypatch):
    monkeypatch.setattr(reply_sim, "rng", ScriptedRng(outcome="hired"))
    assert reply_sim.simulate_reply(0.09, GOOD_PREFS, "Great proposal", ["python"]) == "no_reply"


def test_missing_required_skills_gets_no_reply(monkeypatch):
    monkeypatch.setattr(reply_sim, "rng", ScriptedRng(outcome="hired"))
    assert reply_sim.simulate_reply(0.9, GOOD_PREFS, "Great proposal", ["vue"]) == "no_reply"


def test_generic_opener_gets_no_reply(monkeypatch):
    monkeypatch.setattr(reply_sim, "rng", ScriptedRng(outcome="hired"))
    assert (
        reply_sim.simulate_reply(0.9, GOOD_PREFS, "Dear Hiring Manager, ...", ["python"])
        == "no_reply"
    )


def test_matching_proposal_can_get_replied(monkeypatch):
    monkeypatch.setattr(reply_sim, "rng", ScriptedRng(outcome="replied"))
    assert reply_sim.simulate_reply(0.9, GOOD_PREFS, "I build churn models", ["python"]) == "replied"


def test_interview_can_convert_to_hired(monkeypatch):
    monkeypatch.setattr(reply_sim, "rng", ScriptedRng(outcome="interview", roll=0.1))
    assert reply_sim.simulate_reply(0.9, GOOD_PREFS, "I build churn models", ["python"]) == "hired"


def test_interview_can_stay_interview(monkeypatch):
    monkeypatch.setattr(reply_sim, "rng", ScriptedRng(outcome="interview", roll=0.9))
    assert reply_sim.simulate_reply(0.9, GOOD_PREFS, "I build churn models", ["python"]) == "interview"


async def test_submitted_proposal_receives_client_reply(api_factory, monkeypatch):
    api = await api_factory(reply_delay_min_seconds=0.0, reply_delay_max_seconds=0.0)
    monkeypatch.setattr(reply_sim, "rng", ScriptedRng(outcome="replied"))
    response = await api.post(
        "/proposals",
        json={
            "job_id": "job_ml",
            "cover_letter": "I have shipped churn models with python.",
            "skills_mentioned": ["python"],
            "idempotency_key": "reply-1",
        },
        headers=AUTH_ML,
    )
    assert response.status_code == 201
    await drain()

    proposals = (await api.get("/proposals", headers=AUTH_ML)).json()
    assert proposals[0]["status"] == "replied"

    messages = (
        await api.get("/messages", params={"conversation_id": "job_ml:ml_engineer"}, headers=AUTH_ML)
    ).json()
    assert len(messages) == 1
    assert messages[0]["sender"] == "client"
    assert "churn model" in messages[0]["body"]


async def test_bad_actor_client_never_replies(api_factory, monkeypatch):
    api = await api_factory(reply_delay_min_seconds=0.0, reply_delay_max_seconds=0.0)
    monkeypatch.setattr(reply_sim, "rng", ScriptedRng(outcome="hired"))
    response = await api.post(
        "/proposals",
        json={
            "job_id": "job_scam",
            "cover_letter": "I can build this dashboard with python.",
            "skills_mentioned": ["dashboarding"],
            "idempotency_key": "reply-2",
        },
        headers=AUTH_ML,
    )
    assert response.status_code == 201
    await drain()

    proposals = (await api.get("/proposals", headers=AUTH_ML)).json()
    assert proposals[0]["status"] == "no_reply"
    messages = (
        await api.get("/messages", params={"conversation_id": "job_scam:ml_engineer"}, headers=AUTH_ML)
    ).json()
    assert messages == []


async def test_hired_closes_the_job(api_factory, monkeypatch):
    api = await api_factory(reply_delay_min_seconds=0.0, reply_delay_max_seconds=0.0)
    monkeypatch.setattr(reply_sim, "rng", ScriptedRng(outcome="interview", roll=0.1))
    await api.post(
        "/proposals",
        json={
            "job_id": "job_ml",
            "cover_letter": "I have shipped churn models with python.",
            "skills_mentioned": ["python"],
            "idempotency_key": "reply-3",
        },
        headers=AUTH_ML,
    )
    await drain()

    job = (await api.get("/jobs/job_ml", headers=AUTH_ML)).json()
    assert job["status"] == "filled"
    proposals = (await api.get("/proposals", headers=AUTH_ML)).json()
    assert proposals[0]["status"] == "hired"

    response = await api.post(
        "/proposals",
        json={
            "job_id": "job_ml",
            "cover_letter": "Another proposal.",
            "skills_mentioned": ["python"],
            "idempotency_key": "reply-4",
        },
        headers=AUTH_ML,
    )
    assert response.status_code == 409
