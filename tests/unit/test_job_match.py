"""Job-to-persona ranking."""

from agent.job_match import rank_jobs


def job(id, title, skills, category="Web Development", description=""):
    return {
        "id": id,
        "title": title,
        "skills": skills,
        "category": category,
        "description": description or title,
    }


def pool(extra):
    # Plenty of unrelated jobs so skill frequencies and categories are meaningful.
    filler = [
        job(f"m{i}", f"Marketing task {i}", ["seo", "python"], "Marketing")
        for i in range(30)
    ]
    web = [
        job(f"w{i}", f"Web task {i}", ["javascript"], "Web Development")
        for i in range(12)
    ]
    return filler + web + extra


def test_specific_skills_beat_generic_ones():
    jobs = pool(
        [
            job("generic", "Python script", ["python"], "Marketing"),
            job("specific", "PyTorch model", ["pytorch", "python"], "Marketing"),
        ]
    )
    ranked = rank_jobs(["python", "pytorch"], jobs)
    ids = [item["job"]["id"] for item in ranked]
    assert ids.index("specific") < ids.index("generic")
    assert ranked[ids.index("specific")]["matched_skills"] == ["python", "pytorch"]


def test_a_skill_tag_alone_does_not_make_an_unrelated_job_match():
    noisy = job(
        "noisy",
        "Set up affiliate partnerships",
        ["pytorch"],
        "Marketing",
        "Find publishers.",
    )
    # Real ML jobs exist elsewhere, so "AI & Machine Learning" is the home category.
    real = [
        job(f"ml{i}", f"PyTorch model {i}", ["pytorch"], "AI & Machine Learning")
        for i in range(12)
    ]
    ids = [item["job"]["id"] for item in rank_jobs(["pytorch"], pool(real + [noisy]), limit=50)]
    assert "noisy" not in ids and len(ids) == 12


def test_excluded_jobs_never_appear_but_still_count_for_statistics():
    scam = job("scam", "PyTorch model", ["pytorch"])
    ok = job("ok", "PyTorch model", ["pytorch"])
    ranked = rank_jobs(
        ["pytorch"], pool([scam, ok]), exclude=lambda j: j["id"] == "scam"
    )
    assert [item["job"]["id"] for item in ranked] == ["ok"]


def test_home_category_is_inferred_and_boosts_its_jobs():
    jobs = pool(
        [
            job("react-web", "React app", ["react"], "Web Development", "react app"),
            job("react-mkt", "React app", ["react"], "Marketing", "react app"),
        ]
    )
    ranked = rank_jobs(["react", "javascript"], jobs)
    assert ranked[0]["job"]["id"] == "react-web"
    assert ranked[0]["score"] > ranked[1]["score"]


def test_limit_and_deterministic_order():
    jobs = pool([job(f"j{i}", "React app", ["react"], description="react") for i in range(5)])
    first = rank_jobs(["react"], jobs, limit=3)
    assert len(first) == 3
    assert first == rank_jobs(["react"], jobs, limit=3)


def test_script_leaves_out_scams_injections_and_bad_clients():
    from scripts.match_jobs import compute

    jobs = [
        {**job(f"ok{i}", f"React app {i}", ["react"], description="react"), "client_id": "good"}
        for i in range(12)
    ] + [
        {**job("scam", "React app", ["react"], description="react"), "is_scam": True},
        {**job("inj", "React app", ["react"], description="react"), "has_injection": True},
        {**job("bad", "React app", ["react"], description="react"), "client_id": "evil"},
        {**job("quiet", "React app", ["react"], description="react"), "client_id": "ghost"},
    ]
    clients = [
        {"id": "good", "hire_rate": 0.8},
        {"id": "evil", "hire_rate": 0.9, "is_bad_actor": True},
        {"id": "ghost", "hire_rate": 0.01},
    ]
    result = compute(jobs, clients, {"fullstack_dev": ["react"]}, limit=50)
    ids = {item["job"]["id"] for item in result["fullstack_dev"]}
    assert ids == {f"ok{i}" for i in range(12)}


async def test_script_replaces_a_personas_rows_instead_of_duplicating(tmp_path):
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from apps.api.models import Base, PersonaJobMatch
    from scripts.match_jobs import store

    url = f"sqlite+aiosqlite:///{tmp_path / 'm.db'}"
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    item = lambda id: {
        "job": {"id": id, "title": id, "skills": []},
        "score": 1.0,
        "matched_skills": ["react"],
    }
    await store(url, {"a": [item("j1"), item("j2")], "b": [item("j1")]})
    await store(url, {"a": [item("j2"), item("j3")]})
    async with async_sessionmaker(engine)() as session:
        rows = (await session.execute(select(PersonaJobMatch))).scalars().all()
    await engine.dispose()
    assert sorted((r.persona, r.job_id) for r in rows) == [
        ("a", "j2"),
        ("a", "j3"),
        ("b", "j1"),
    ]
