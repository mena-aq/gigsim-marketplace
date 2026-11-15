import json

from sqlalchemy import func, select

from gigsim.config import Settings
from gigsim.models import Client, Job
from gigsim.seed import seed


def write_fixtures(tmp_path) -> tuple:
    jobs = [
        {
            "id": "j1",
            "title": "Job one",
            "description": "First job",
            "skills": ["python"],
            "budget_min": 100,
            "budget_max": 200,
            "timeline_days": 7,
            "screening_questions": [],
            "category": "General",
            "client_id": "c1",
            "posted_at": "2024-05-01T10:00:00",
            "is_scam": False,
            "has_injection": False,
        },
        {
            "id": "j2",
            "title": "Job two",
            "description": "Second job",
            "skills": ["react"],
            "budget_min": 300,
            "budget_max": 600,
            "timeline_days": 14,
            "screening_questions": ["Timeline?"],
            "category": "Web Development",
            "client_id": "c1",
            "posted_at": "2024-06-01T10:00:00",
            "is_scam": True,
            "has_injection": False,
        },
    ]
    stream = [
        {
            "id": "s1",
            "title": "Stream job",
            "description": "Later",
            "skills": ["nlp"],
            "budget_min": 400,
            "budget_max": 900,
            "timeline_days": 10,
            "screening_questions": [],
            "category": "AI",
            "client_id": "c1",
            "posted_at": "2024-07-01T10:00:00",
            "is_scam": False,
            "has_injection": True,
        }
    ]
    clients = [
        {
            "id": "c1",
            "name": "Fixture Client",
            "total_spend": 1000.0,
            "hire_rate": 0.5,
            "avg_rating": 4.5,
            "payment_verified": True,
            "hidden_preferences": {
                "must_have_skills": ["python"],
                "budget_ceiling": 2000,
                "dislikes": ["copy-pasted cover letters"],
            },
            "reviews": ["Great client."],
        }
    ]
    (tmp_path / "jobs.json").write_text(json.dumps(jobs))
    (tmp_path / "stream_jobs.json").write_text(json.dumps(stream))
    (tmp_path / "clients.json").write_text(json.dumps(clients))
    return tmp_path / "jobs.json", tmp_path / "stream_jobs.json", tmp_path / "clients.json"


async def test_seed_loads_and_is_idempotent(tmp_path):
    jobs_path, stream_path, clients_path = write_fixtures(tmp_path)
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'gigsim.db'}"
    settings = Settings(
        database_url=database_url,
        admin_token="test-admin",
        token_ml_engineer="test-token-ml",
        token_fullstack_dev="test-token-fullstack",
        token_data_analyst="test-token-data",
        _env_file=None,
    )

    summary = await seed(settings, jobs_path, stream_path, clients_path)
    assert summary["seed_jobs"] == 2
    assert summary["stream_jobs"] == 1
    assert summary["clients"] == 1

    from gigsim.db import build_engine, build_sessionmaker

    engine = build_engine(database_url)
    sessionmaker = build_sessionmaker(engine)
    async with sessionmaker() as session:
        job_count = (await session.execute(select(func.count(Job.id)))).scalar_one()
        client_count = (await session.execute(select(func.count(Client.id)))).scalar_one()
        statuses = dict(
            (await session.execute(select(Job.id, Job.status))).all()
        )
    assert job_count == 3
    assert client_count == 1
    assert statuses == {"j1": "open", "j2": "open", "s1": "pending"}

    await seed(settings, jobs_path, stream_path, clients_path)
    async with sessionmaker() as session:
        job_count = (await session.execute(select(func.count(Job.id)))).scalar_one()
    assert job_count == 3
    await engine.dispose()
