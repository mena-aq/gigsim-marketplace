"""Invariants for the generated Phase 0 datasets (skipped when data is not built)."""

import json
from pathlib import Path

import pytest

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"

pytestmark = pytest.mark.skipif(
    not (DATA_DIR / "jobs.json").exists(), reason="run `make process` first"
)


@pytest.fixture(scope="module")
def dataset():
    jobs = json.loads((DATA_DIR / "jobs.json").read_text())
    stream = json.loads((DATA_DIR / "stream_jobs.json").read_text())
    clients = json.loads((DATA_DIR / "clients.json").read_text())
    outcomes = json.loads((DATA_DIR / "outcomes.json").read_text())
    return jobs, stream, clients, outcomes


def test_dataset_sizes(dataset):
    jobs, stream, clients, _ = dataset
    assert len(jobs) == 1200
    assert len(stream) == 300
    assert len(clients) == 200


def test_seed_and_stream_jobs_are_disjoint(dataset):
    jobs, stream, _, _ = dataset
    assert not {job["id"] for job in jobs} & {job["id"] for job in stream}


def test_every_job_has_two_or_three_skills(dataset):
    jobs, stream, _, _ = dataset
    for job in jobs + stream:
        assert 2 <= len(job["skills"]) <= 3, job["id"]
        assert all(skill.strip() for skill in job["skills"])


def test_clients_have_two_or_three_must_have_skills(dataset):
    _, _, clients, _ = dataset
    for client in clients:
        must_have = client["hidden_preferences"]["must_have_skills"]
        assert 2 <= len(must_have) <= 3, client["id"]


def test_bad_actor_rate_and_flag(dataset):
    _, _, clients, _ = dataset
    assert all("is_bad_actor" in client for client in clients)
    bad_actors = [client for client in clients if client["is_bad_actor"]]
    assert len(bad_actors) == round(0.05 * len(clients))
    assert all(client["hire_rate"] < 0.1 for client in bad_actors)


def test_scam_and_injection_rates(dataset):
    jobs, stream, _, _ = dataset
    total = len(jobs) + len(stream)
    scams = sum(job["is_scam"] for job in jobs + stream)
    injections = sum(job["has_injection"] for job in jobs + stream)
    assert 0.08 <= scams / total <= 0.12
    assert 0.015 <= injections / total <= 0.025


def test_outcome_distributions_sum_to_one(dataset):
    _, _, _, outcomes = dataset
    for distribution in [outcomes["overall"], *outcomes["by_category"].values()]:
        assert sum(distribution.values()) == pytest.approx(1.0, abs=0.01)
