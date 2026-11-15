"""Load data/processed JSON into the GigSim database. Idempotent.

Usage:  python -m gigsim.seed [--jobs PATH] [--stream PATH] [--clients PATH]
                                     [--database-url URL] [--reset]

Default paths point at data/processed (written by data/scripts/process.py).
Upserts by id: re-running never duplicates rows and never touches existing
proposals, messages, connects or audit entries. --reset drops every table
first, for a clean reseed after the processed data changes.
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from gigsim.config import Settings
from gigsim.db import build_engine, build_sessionmaker, init_db
from gigsim.models import Client, Connects, Job

REPO_ROOT = Path(__file__).resolve().parents[1]


def parse_job(record: dict, status: str) -> Job:
    return Job(
        id=record["id"],
        title=record["title"],
        description=record["description"],
        skills=record.get("skills", []),
        budget_min=record.get("budget_min"),
        budget_max=record.get("budget_max"),
        timeline_days=record.get("timeline_days"),
        screening_questions=record.get("screening_questions", []),
        category=record.get("category"),
        client_id=record.get("client_id"),
        posted_at=(
            datetime.fromisoformat(record["posted_at"]) if record.get("posted_at") else None
        ),
        is_scam=bool(record.get("is_scam", False)),
        has_injection=bool(record.get("has_injection", False)),
        status=status,
    )


def parse_client(record: dict) -> Client:
    return Client(
        id=record["id"],
        name=record["name"],
        total_spend=record.get("total_spend", 0.0),
        hire_rate=record.get("hire_rate", 0.0),
        avg_rating=record.get("avg_rating", 0.0),
        payment_verified=bool(record.get("payment_verified", False)),
        is_bad_actor=bool(record.get("is_bad_actor", False)),
        hidden_preferences=record.get("hidden_preferences", {}),
        reviews=record.get("reviews", []),
    )


async def seed(settings: Settings, jobs_path: Path, stream_path: Path,
               clients_path: Path, reset: bool = False) -> dict:
    engine = build_engine(settings.database_url)
    sessionmaker = build_sessionmaker(engine)
    if reset:
        from gigsim.models import Base

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    await init_db(engine)

    jobs = json.loads(jobs_path.read_text())
    stream_jobs = json.loads(stream_path.read_text())
    clients = json.loads(clients_path.read_text())

    async with sessionmaker() as session:
        for record in clients:
            await session.merge(parse_client(record))
        for record in jobs:
            await session.merge(parse_job(record, status="open"))
        for record in stream_jobs:
            await session.merge(parse_job(record, status="pending"))
        for freelancer_id in settings.freelancer_tokens:
            existing = await session.get(Connects, freelancer_id)
            if existing is None:
                session.add(
                    Connects(freelancer_id=freelancer_id, balance=settings.initial_connects)
                )
        await session.commit()

    await engine.dispose()
    return {
        "seed_jobs": len(jobs),
        "stream_jobs": len(stream_jobs),
        "clients": len(clients),
        "freelancers": list(settings.freelancer_tokens),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jobs", default=str(REPO_ROOT / "data" / "processed" / "jobs.json"))
    parser.add_argument("--stream", default=str(REPO_ROOT / "data" / "processed" / "stream_jobs.json"))
    parser.add_argument("--clients", default=str(REPO_ROOT / "data" / "processed" / "clients.json"))
    parser.add_argument("--database-url", default=None, help="override GIGSIM_DATABASE_URL")
    parser.add_argument("--reset", action="store_true",
                        help="drop all tables before seeding (clean reseed)")
    args = parser.parse_args()

    if args.database_url:
        settings = Settings(database_url=args.database_url, _env_file=None)
    else:
        settings = Settings()

    jobs_path, stream_path, clients_path = Path(args.jobs), Path(args.stream), Path(args.clients)
    for path in (jobs_path, stream_path, clients_path):
        if not path.exists():
            print(f"[error] {path} not found — run `make process` first.", file=sys.stderr)
            return 1

    summary = asyncio.run(seed(settings, jobs_path, stream_path, clients_path, reset=args.reset))
    print(
        f"[seed] loaded {summary['seed_jobs']} open jobs, "
        f"{summary['stream_jobs']} pending stream jobs, {summary['clients']} clients\n"
        f"[seed] freelancer connects ready for: {', '.join(summary['freelancers'])}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
