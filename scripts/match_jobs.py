"""Store the best-fitting open jobs for each persona so the app can recommend them.

Usage:  python -m scripts.match_jobs [--per-persona N] [--database-url URL]

Reads the processed job pool and each persona's skills file, ranks jobs with
agent.job_match, and replaces that persona's rows in persona_job_matches. Scams,
injected posts and bad-actor or near-zero-hire-rate clients are left out of the
recommendations only; the full job inbox still shows every job. Re-running is safe.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from agent.job_match import rank_jobs
from apps.api.config import Settings
from apps.api.db import build_engine
from apps.api.models import PersonaJobMatch

ROOT = Path(__file__).resolve().parents[1]
JOB_FIELDS = (
    "id",
    "title",
    "description",
    "skills",
    "budget_min",
    "budget_max",
    "timeline_days",
    "screening_questions",
    "category",
)


def persona_skills(personas_dir: Path) -> dict[str, list[str]]:
    skills = {}
    for path in sorted(personas_dir.glob("*/skills.json")):
        skills[path.parent.name] = json.loads(path.read_text())["skills"]
    return skills


def excluder(clients: list[dict]):
    unsafe = {
        client["id"]
        for client in clients
        if client.get("is_bad_actor") or client.get("hire_rate", 1.0) < 0.1
    }

    def exclude(job: dict) -> bool:
        return (
            bool(job.get("is_scam"))
            or bool(job.get("has_injection"))
            or job.get("client_id") in unsafe
        )

    return exclude


def compute(
    jobs: list[dict], clients: list[dict], skills: dict[str, list[str]], limit: int
) -> dict[str, list[dict]]:
    exclude = excluder(clients)
    return {
        persona: rank_jobs(persona_skills_list, jobs, exclude=exclude, limit=limit)
        for persona, persona_skills_list in skills.items()
    }


async def store(database_url: str, matches: dict[str, list[dict]]) -> None:
    engine = build_engine(database_url)
    async with async_sessionmaker(engine)() as session, session.begin():
        for persona, items in matches.items():
            await session.execute(
                delete(PersonaJobMatch).where(PersonaJobMatch.persona == persona)
            )
            session.add_all(
                PersonaJobMatch(
                    persona=persona,
                    job_id=item["job"]["id"],
                    score=item["score"],
                    matched_skills=item["matched_skills"],
                    job={field: item["job"].get(field) for field in JOB_FIELDS},
                )
                for item in items
            )
    await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--per-persona", type=int, default=12)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--jobs", default=str(ROOT / "data/processed/jobs.json"))
    parser.add_argument("--clients", default=str(ROOT / "data/processed/clients.json"))
    parser.add_argument("--personas", default=str(ROOT / "data/personas"))
    args = parser.parse_args()
    for path in (args.jobs, args.clients, args.personas):
        if not Path(path).exists():
            print(f"[error] {path} not found", file=sys.stderr)
            return 1
    jobs = json.loads(Path(args.jobs).read_text())
    clients = json.loads(Path(args.clients).read_text())
    skills = persona_skills(Path(args.personas))
    matches = compute(jobs, clients, skills, args.per_persona)
    settings = (
        Settings(database_url=args.database_url, _env_file=None)
        if args.database_url
        else Settings()
    )
    asyncio.run(store(settings.database_url, matches))
    for persona, items in matches.items():
        print(f"[match-jobs] {persona}: {len(items)} jobs")
        for item in items[:5]:
            print(
                f"    {item['score']:6.1f}  {item['job']['title'][:55]:<55}"
                f"  {', '.join(item['matched_skills'])}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
