"""Simulator receipt compatibility and safe retry behavior."""

from gigsim.tests.conftest import AUTH_ML
from gigsim.tests.test_proposals import proposal_payload


async def test_message_key_replay_and_conflict(api):
    await api.post(
        "/proposals", json=proposal_payload(idempotency_key="setup"), headers=AUTH_ML
    )
    payload = {
        "conversation_id": "job_ml:ml_engineer",
        "body": "Hello",
        "idempotency_key": "message-one",
    }
    first = await api.post("/messages", json=payload, headers=AUTH_ML)
    replay = await api.post("/messages", json=payload, headers=AUTH_ML)
    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    conflict = await api.post(
        "/messages", json={**payload, "body": "Different"}, headers=AUTH_ML
    )
    assert conflict.status_code == 409
    messages = await api.get(
        "/messages",
        params={"conversation_id": payload["conversation_id"]},
        headers=AUTH_ML,
    )
    assert len(messages.json()) == 1


async def test_proposal_key_conflict_does_not_spend(api):
    payload = proposal_payload(idempotency_key="same")
    first = await api.post("/proposals", json=payload, headers=AUTH_ML)
    balance = (await api.get("/connects", headers=AUTH_ML)).json()["balance"]
    conflict = await api.post(
        "/proposals", json={**payload, "cover_letter": "Different"}, headers=AUTH_ML
    )
    assert first.status_code == 201
    assert conflict.status_code == 409
    assert (await api.get("/connects", headers=AUTH_ML)).json()["balance"] == balance
