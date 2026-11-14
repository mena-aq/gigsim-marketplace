"""Rank open jobs by how well they fit a persona's skills. Pure; no I/O.

Rarer skills count more than common ones (`pytorch` over `python`), because the job
pool is mostly unrelated marketing and design work and generic skills match almost
everything. A job must mention at least one persona skill in its own text, so a noisy
skill tag alone cannot put an unrelated job on top. The persona's home category is
inferred from the data (the category whose jobs fit the skills best), not hard-coded.
"""

import math
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable

CATEGORY_BONUS = 20.0
MIN_CATEGORY_JOBS = 10


def _mentions(skill: str, text: str) -> bool:
    return bool(re.search(r"(?<![\w.])" + re.escape(skill) + r"(?![\w])", text))


class Ranker:
    def __init__(self, jobs: Iterable[dict]):
        self.jobs = list(jobs)
        self.total = len(self.jobs)
        self.frequency = Counter(
            skill.lower() for job in self.jobs for skill in set(job.get("skills") or [])
        )

    def weight(self, skill: str) -> float:
        return math.log((self.total + 1) / (self.frequency.get(skill, 0) + 1))

    def fit(self, skills: Iterable[str], job: dict) -> tuple[float, list[str], int]:
        have = {skill.lower() for skill in skills}
        tagged = {skill.lower() for skill in job.get("skills") or []}
        text = f"{job.get('title', '')} {job.get('description', '')}".lower()
        mentioned = {skill for skill in have if _mentions(skill, text)}
        overlap = have & tagged
        score = sum(self.weight(s) for s in overlap) + 2 * sum(
            self.weight(s) for s in mentioned
        )
        return score, sorted(overlap | mentioned), len(mentioned)

    def home_category(self, skills: Iterable[str]) -> str | None:
        by_category: dict[str, list[float]] = defaultdict(list)
        for job in self.jobs:
            if job.get("category"):
                by_category[job["category"]].append(self.fit(skills, job)[0])
        means = {
            category: sum(values) / len(values)
            for category, values in by_category.items()
            if len(values) >= MIN_CATEGORY_JOBS
        }
        return max(means, key=means.get) if means else None


def rank_jobs(
    skills: Iterable[str],
    jobs: Iterable[dict],
    *,
    exclude: Callable[[dict], bool] = lambda job: False,
    limit: int = 12,
) -> list[dict]:
    """Best-fitting jobs first. `exclude` removes jobs (scams, bad clients) from the
    results but not from the statistics the ranking is calibrated on."""
    skills = list(skills)
    ranker = Ranker(jobs)
    home = ranker.home_category(skills)
    ranked = []
    for job in ranker.jobs:
        if exclude(job):
            continue
        score, matched, mentions = ranker.fit(skills, job)
        in_home = home is not None and job.get("category") == home
        if mentions < 1 and not (in_home and matched):
            continue
        ranked.append(
            {
                "job": job,
                "score": round(score + (CATEGORY_BONUS if in_home else 0.0), 2),
                "matched_skills": matched,
                "category": job.get("category"),
            }
        )
    ranked.sort(key=lambda item: (-item["score"], str(item["job"].get("id"))))
    return ranked[:limit]
