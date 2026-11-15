"""Coherent, seeded job/client assignment, shared by processing and data repair."""

import hashlib
import random


def required_skills(client: dict) -> set[str]:
    """Read flat generation profiles and finalized simulator profiles alike."""
    preferences = client.get("hidden_preferences", client)
    return {
        s.strip().casefold()
        for s in preferences.get("must_have_skills", [])
        if s.strip()
    }


def job_skills(job: dict) -> set[str]:
    return {s.strip().casefold() for s in job.get("skills", []) if s.strip()}


def ensure_client_coverage(
    jobs: list[dict], clients: list[dict], seed: int = 42
) -> list[dict]:
    """Add reusable category-specific profiles for otherwise uncovered skills."""
    added = []
    covered = (
        set().union(*(required_skills(client) for client in clients))
        if clients
        else set()
    )
    for job in sorted(jobs, key=lambda item: item["id"]):
        skills = job_skills(job)
        if not skills or skills & covered:
            continue
        key = (job.get("category") or "General") + "|" + "|".join(sorted(skills))
        digest = hashlib.sha256(key.encode()).hexdigest()[:12]
        rng = random.Random(f"{seed}:{key}")
        hires = rng.randint(1, 30)
        client = {
            "id": f"client_coverage_{digest}",
            "name": f"{job.get('category') or 'General'} Project Team",
            "total_spend": round(rng.uniform(500, 50000), 2),
            "hires": hires,
            "hire_rate": round(min(0.95, max(0.05, hires / (hires + 5))), 2),
            "avg_rating": round(rng.uniform(3.4, 5), 1),
            "payment_verified": rng.random() > 0.15,
            "must_have_skills": sorted(skills)[:3],
            "budget_ceiling": job.get("budget_max") or 1000,
            "categories": [job.get("category") or "General"],
        }
        clients.append(client)
        added.append(client)
        covered.update(required_skills(client))
    return added


def assign_clients(jobs: list[dict], clients: list[dict], seed: int = 42) -> dict:
    """Weight by hiring history among compatible clients, never observed replies."""
    rng = random.Random(seed)
    if not clients:
        raise ValueError("Client assignment requires profiles")
    empty = 0
    for job in sorted(jobs, key=lambda item: item["id"]):
        skills = job_skills(job)
        candidates = (
            [client for client in clients if skills & required_skills(client)]
            if skills
            else clients
        )
        if not candidates:
            raise ValueError(
                f"No compatible client for {job['id']}; ensure coverage first"
            )
        if not skills:
            empty += 1
        weights = [
            max(1, c.get("hires", round(c.get("hire_rate", 0) * 30)))
            for c in candidates
        ]
        job["client_id"] = rng.choices(candidates, weights=weights)[0]["id"]
    return {
        "jobs": len(jobs),
        "clients": len(clients),
        "jobs_without_skills": empty,
        "assignment": "seeded hiring-history weights among skill-compatible clients",
    }
