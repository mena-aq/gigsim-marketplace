"""Rule-based client reply simulator.

Given a client's hidden preferences and a submitted proposal, decide how the client
reacts: no_reply | replied | interview | hired. Deterministic rules first, weighted
random choice at the end (monkeypatch `rng` in tests).
"""

import random

rng = random.Random()

WEIGHTS = {"no_reply": 0.50, "replied": 0.35, "interview": 0.15}
HIRE_CHANCE_AFTER_INTERVIEW = 0.30


def simulate_reply(
    hire_rate: float,
    hidden_preferences: dict,
    cover_letter: str,
    skills_mentioned: list[str],
) -> str:
    if hire_rate < 0.1:
        return "no_reply"
    required = {s.lower() for s in hidden_preferences.get("must_have_skills", [])}
    mentioned = {s.lower() for s in skills_mentioned}
    if required and not required.intersection(mentioned):
        return "no_reply"
    if "dear hiring manager" in cover_letter.lower():
        return "no_reply"
    outcome = rng.choices(list(WEIGHTS), weights=list(WEIGHTS.values()))[0]
    if outcome == "interview" and rng.random() < HIRE_CHANCE_AFTER_INTERVIEW:
        return "hired"
    return outcome


def client_message(outcome: str, client_name: str, job_title: str) -> str:
    templates = {
        "replied": (
            "Hi, thanks for your proposal on \"{job}\". It caught our attention — "
            "could you share a bit more detail on how you would approach the first milestone?"
        ),
        "interview": (
            "Hello! We reviewed your proposal for \"{job}\" and would like to schedule "
            "a short interview this week to discuss scope and timeline. Does that work for you?"
        ),
        "hired": (
            "Great news — we'd like to move forward with you on \"{job}\". "
            "We'll send the contract and milestones shortly. Welcome aboard!"
        ),
    }
    return templates.get(outcome, "").format(job=job_title)
