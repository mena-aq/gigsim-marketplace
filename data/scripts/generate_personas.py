"""Generate freelancer persona corpora (CV, case studies, proposals, reviews).

Two ways to generate:
  1. Directly via an LLM provider (auto: Ollama -> Groq -> none), batched to
     stay inside free-tier token limits:
       python data/scripts/generate_personas.py [--provider groq]
  2. Via any free web chat UI (ChatGPT/Gemini/Claude), no API needed:
       python data/scripts/generate_personas.py --emit-prompts
       # paste each file in data/personas/_prompts/ into a chat, save the
       # whole reply as data/personas/_inbox/<same-name>.txt
       python data/scripts/generate_personas.py --import-inbox

Defaults per persona: 50 proposals, 8 case studies, 6 reviews (AGENT.md allows
15-20 / 100-150 / 10-15; pass --limit, --case-studies-limit and --reviews-count
to scale up). Output: data/personas/{persona_id}/. Idempotent: existing files
are skipped unless --force is given, and a quota-truncated run resumes where it
stopped.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from datetime import date, timedelta
from pathlib import Path

try:
    from llm_client import (
        QuotaExhausted,
        chat,
        describe,
        load_env_file,
        provider,
        usage_summary,
    )
except ImportError:  # imported as a package module rather than a script
    from data.scripts.llm_client import (
        QuotaExhausted,
        chat,
        describe,
        load_env_file,
        provider,
        usage_summary,
    )

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = REPO_ROOT / "data" / "scripts" / "prompts"

DEFAULT_OUTCOMES = {"won": 0.15, "replied": 0.4, "ignored": 0.45}

CASE_STUDY_BATCH = 6
PROPOSAL_BATCH = 10
DEFAULT_PROPOSALS = 50
DEFAULT_CASE_STUDIES = 8
DEFAULT_REVIEWS = 6

PERSONAS: dict[str, dict] = {
    "ml_engineer": {
        "display_name": "Maya Chen",
        "headline": "Machine learning engineer specialising in production NLP and forecasting",
        "hourly_rate": 65,
        "availability_hours": 30,
        "skills": [
            "python", "pytorch", "scikit-learn", "pandas", "nlp", "transformers",
            "sql", "fastapi", "docker", "mlflow", "spacy", "langchain", "numpy",
        ],
        "categories": ["ai & machine learning", "data science"],
        "case_studies": [
            ("Fraud detection pipeline for a payments startup", ["python", "scikit-learn", "mlflow"]),
            ("Customer churn model for a subscription app", ["python", "pytorch", "pandas"]),
            ("Product recommendation engine for e-commerce", ["python", "numpy", "sql"]),
            ("Document classification service for a law firm", ["python", "transformers", "fastapi"]),
            ("Demand forecasting for a retail chain", ["python", "scikit-learn", "pandas"]),
            ("Sentiment analysis dashboard for support tickets", ["python", "nlp", "spacy"]),
            ("Image classification service for inventory photos", ["python", "pytorch", "docker"]),
            ("Anomaly detection on platform logs", ["python", "pandas", "scikit-learn"]),
            ("Lead scoring model for a B2B sales team", ["python", "scikit-learn", "sql"]),
            ("Chatbot intent classifier for a telco", ["python", "transformers", "langchain"]),
            ("House price prediction model for a portal", ["python", "scikit-learn", "pandas"]),
            ("Speech-to-text pipeline for podcast archives", ["python", "transformers", "docker"]),
            ("RAG search over internal wikis", ["python", "langchain", "transformers"]),
            ("Energy consumption time-series forecast", ["python", "pytorch", "pandas"]),
            ("Named entity extraction for legal contracts", ["python", "spacy", "nlp"]),
            ("Uplift model for marketing campaigns", ["python", "scikit-learn", "numpy"]),
            ("Customer segmentation clustering study", ["python", "pandas", "scikit-learn"]),
            ("Model monitoring and retraining pipeline", ["python", "mlflow", "docker"]),
        ],
    },
    "fullstack_dev": {
        "display_name": "Daniel Okafor",
        "headline": "Full-stack developer building fast web products with React and TypeScript",
        "hourly_rate": 55,
        "availability_hours": 35,
        "skills": [
            "react", "typescript", "node.js", "next.js", "postgresql", "prisma",
            "tailwind css", "graphql", "docker", "redis", "jest", "python", "css",
        ],
        "categories": ["web development", "mobile development"],
        "case_studies": [
            ("SaaS booking platform for a clinic chain", ["react", "typescript", "postgresql"]),
            ("E-commerce storefront with Stripe checkout", ["next.js", "typescript", "stripe"]),
            ("Real estate listing portal with map search", ["react", "node.js", "postgresql"]),
            ("Internal admin dashboard for logistics", ["react", "typescript", "graphql"]),
            ("Restaurant ordering PWA", ["react", "node.js", "tailwind css"]),
            ("Fitness tracking web app", ["react", "typescript", "prisma"]),
            ("Job board platform with employer accounts", ["next.js", "postgresql", "prisma"]),
            ("Payment portal integration for invoicing", ["node.js", "typescript", "stripe"]),
            ("CRM integration tool for a sales team", ["node.js", "graphql", "react"]),
            ("Inventory management system for retail", ["react", "postgresql", "prisma"]),
            ("Video streaming MVP for a creator", ["react", "node.js", "redis"]),
            ("Multi-tenant blog platform", ["next.js", "typescript", "postgresql"]),
            ("Appointment scheduling API", ["node.js", "graphql", "docker"]),
            ("Learning management portal for a school", ["react", "node.js", "postgresql"]),
            ("Social analytics tool with charts", ["react", "typescript", "css"]),
            ("Referral program with QR codes", ["next.js", "node.js", "tailwind css"]),
            ("Secure file-sharing app with auth", ["react", "node.js", "docker"]),
            ("API gateway refactor for a fintech", ["node.js", "redis", "docker"]),
        ],
    },
    "data_analyst": {
        "display_name": "Priya Sharma",
        "headline": "Data analyst turning messy data into dashboards and decisions",
        "hourly_rate": 45,
        "availability_hours": 25,
        "skills": [
            "sql", "python", "excel", "tableau", "power bi", "pandas",
            "statistics", "dbt", "google analytics", "data visualization", "r",
        ],
        "categories": ["data science"],
        "case_studies": [
            ("Sales dashboard in Power BI for a distributor", ["power bi", "sql", "excel"]),
            ("Marketing attribution model for an agency", ["python", "google analytics", "sql"]),
            ("Churn cohort analysis for a SaaS", ["sql", "python", "pandas"]),
            ("Warehouse data cleanup with dbt", ["dbt", "sql", "python"]),
            ("Excel to SQL migration for finance team", ["excel", "sql", "python"]),
            ("Customer segmentation study for retail", ["python", "pandas", "statistics"]),
            ("A/B test analysis report for product", ["statistics", "python", "pandas"]),
            ("Financial KPI reporting pack", ["excel", "sql", "power bi"]),
            ("Supply chain spend analysis", ["sql", "tableau", "excel"]),
            ("Survey data analysis for research", ["python", "statistics", "r"]),
            ("Google Analytics audit for a publisher", ["google analytics", "sql", "excel"]),
            ("Cohort retention dashboard in Tableau", ["tableau", "sql", "python"]),
            ("Revenue forecasting model in sheets", ["excel", "statistics", "python"]),
            ("Automated operations metrics pipeline", ["python", "sql", "dbt"]),
            ("Market research report for expansion", ["python", "statistics", "excel"]),
            ("Data quality audit for a marketplace", ["sql", "python", "pandas"]),
        ],
    },
}

JOB_TITLES: dict[str, list[str]] = {
    "ai & machine learning": [
        "Build a churn prediction model", "NLP classifier for support tickets",
        "Fine-tune an LLM for our docs", "Forecast sales with ML",
        "Recommendation system for our store", "Anomaly detection for IoT logs",
        "Image tagging model for our catalog", "Lead scoring model setup",
    ],
    "web development": [
        "React dashboard for internal tooling", "Next.js marketing site with CMS",
        "Stripe checkout integration", "Marketplace MVP build",
        "Booking system with calendar sync", "Redesign our admin panel",
        "GraphQL API for mobile app", "Fix performance on a React app",
    ],
    "mobile development": [
        "Flutter app for field workers", "React Native e-commerce app",
        "Kotlin app update and bug fixes", "Cross-platform fitness app MVP",
    ],
    "data science": [
        "SQL data warehouse cleanup", "Power BI sales dashboard",
        "Cohort retention analysis", "Excel model rebuild",
        "A/B test results analysis", "Tableau dashboard for marketing",
        "Customer segmentation analysis", "Automate weekly reporting",
    ],
}

TONES = [
    "warm but concise", "direct and technical", "enthusiastic and detailed",
    "professional and measured", "friendly and conversational",
    "brief and to the point", "structured with short bullets",
]

LENGTHS = ["about 120 words", "about 180 words", "about 250 words", "3 short paragraphs"]

PROPOSAL_RULES = """Rules:
- First person, addressed to the client ("Hi", "Hello" — never "Dear Hiring Manager" unless told otherwise).
- Reference 1-2 concrete past projects and specific tools, with realistic but modest numbers.
- Answer the likely screening question for this kind of job in one sentence.
- No contact details, no off-platform requests, no guaranteed outcomes.
- Do not mention the client or company by name.
- Do not mention the job's budget or quote a price; the client's post already states it.
- Do not use placeholders like [Your Name]; if you sign off, use only the freelancer's first name.
- Inside each FILE block output only the proposal body: no frontmatter, no headings, no commentary."""

FILE_MARKER = re.compile(r"(?m)^\s*===\s*FILE:\s*(.+?)\s*===\s*$")
PROPOSAL_PATH = re.compile(
    r"^(?P<persona>[^/]+)/proposals/(?P<outcome>won|replied|ignored)_(?P<index>\d{3})\.md$"
)


# ---------------------------------------------------------------------- helpers


def load_outcomes(out_dir: Path) -> dict:
    path = out_dir / "outcomes.json"
    if path.exists():
        data = json.loads(path.read_text())
        return {"overall": data.get("overall", DEFAULT_OUTCOMES),
                "by_category": data.get("by_category", {})}
    return {"overall": DEFAULT_OUTCOMES, "by_category": {}}


def sample_outcome(rng: random.Random, outcomes: dict, category: str) -> str:
    dist = outcomes["by_category"].get(category) or outcomes["overall"]
    return rng.choices(list(dist), weights=list(dist.values()))[0]


def render_template(name: str, **fields: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text().format(**fields)


def frontmatter(meta: dict) -> str:
    lines = ["---"]
    for key, value in meta.items():
        if isinstance(value, str) and (" " in value or not value):
            value = f'"{value}"'
        lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


def write_if_missing(path: Path, content: str, force: bool) -> bool:
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n")
    return True


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:60]


def case_study_filename(index: int, project_name: str) -> str:
    return f"case_studies/{index:03d}_{slug(project_name)}.md"


def proposal_plan(persona_id: str, index: int, spec: dict, outcomes: dict) -> dict:
    """Deterministic metadata for one proposal (shared by generate/emit/import)."""
    rng = random.Random(f"{persona_id}:proposal:{index}")
    category = rng.choice(spec["categories"])
    outcome = sample_outcome(rng, outcomes, category)
    proposal_date = date(2024, 1, 1) + timedelta(days=rng.randint(0, 545))
    return {
        "index": index,
        "outcome": outcome,
        "category": category,
        "job_title": rng.choice(JOB_TITLES[category]),
        "budget": rng.choice([250, 500, 800, 1200, 2500, 4000]),
        "date": proposal_date.isoformat(),
        "generic_opener": outcome == "ignored" and rng.random() < 0.15,
        "tone": rng.choice(TONES),
        "length": rng.choice(LENGTHS),
        "skills": rng.sample(spec["skills"], min(4, len(spec["skills"]))),
    }


def plan_path(persona_id: str, plan: dict) -> str:
    return f"{persona_id}/proposals/{plan['outcome']}_{plan['index']:03d}.md"


def plan_style_hint(plan: dict) -> str:
    if plan["generic_opener"]:
        return (
            'Open the letter with exactly "Dear Hiring Manager" (the freelancer reused '
            "a template in a hurry; this proposal was ignored)."
        )
    return "Write a natural opener referencing something specific from the job post."


def chunks(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


# --------------------------------------------------------------- static pieces


def write_skills_json(persona_id: str, spec: dict, personas_dir: Path, force: bool) -> bool:
    payload = {
        "persona_id": persona_id,
        "display_name": spec["display_name"],
        "headline": spec["headline"],
        "hourly_rate_usd": spec["hourly_rate"],
        "availability_hours_per_week": spec["availability_hours"],
        "skills": spec["skills"],
    }
    return write_if_missing(personas_dir / persona_id / "skills.json",
                            json.dumps(payload, indent=2), force)


# ------------------------------------------------------------- prompt builders


def build_cv_reviews_prompt(persona_id: str, spec: dict, reviews_count: int) -> str:
    cv_prompt = render_template(
        "cv",
        persona=persona_id,
        display_name=spec["display_name"],
        headline=spec["headline"],
        skills=", ".join(spec["skills"]),
        hourly_rate=spec["hourly_rate"],
        availability=spec["availability_hours"],
        projects="; ".join(name for name, _ in spec["case_studies"][:6]),
    )
    reviews_prompt = render_template(
        "reviews",
        persona=persona_id,
        count=reviews_count,
        display_name=spec["display_name"],
        headline=spec["headline"],
        skills=", ".join(spec["skills"][:8]),
    )
    return f"""# Prompt pack: {persona_id} — CV + client reviews

You are writing synthetic portfolio material for a simulated freelance marketplace.
Follow the instructions exactly. Do not mention real companies, people or clients.

## Task 1 — CV

{cv_prompt}

## Task 2 — Client reviews

{reviews_prompt}

## Output format (strict)

Reply with exactly these two blocks and nothing before or after them.
Do not wrap the whole answer in code fences.

=== FILE: {persona_id}/cv.md ===
<the CV in Markdown>

=== FILE: {persona_id}/reviews.md ===
<one review per line>
"""


def build_case_studies_prompt(persona_id: str, spec: dict,
                              entries: list[tuple[int, tuple[str, list[str]]]],
                              batch_no: int, batch_total: int) -> str:
    project_lines = []
    for position, (index, (project_name, skills)) in enumerate(entries, start=1):
        filename = case_study_filename(index, project_name)
        project_lines.append(
            f"{position}. FILE: {persona_id}/{filename}\n"
            f"   Project: {project_name}\n"
            f"   Skills used: {', '.join(skills)}"
        )
    return f"""# Prompt pack: {persona_id} — case studies (batch {batch_no} of {batch_total})

You are writing synthetic freelance case studies for a {persona_id} freelancer
({spec['headline']}). Write 300-500 words per case study in first person, with
specific tools, numbers and results. Do not mention the client by real name.
Use the structure: what the client needed; what you built and the tools used;
concrete results with numbers; one challenge and how you solved it.

## Studies in this batch

{chr(10).join(project_lines)}

## Output format (strict)

Reply with exactly one block per project listed above, nothing before or after.
Do not wrap the whole answer in code fences.

=== FILE: {persona_id}/case_studies/001_example_name.md ===
# <Project name>

<case study body>
"""


def build_proposals_prompt(persona_id: str, spec: dict, outcomes: dict,
                           indices: list[int], batch_no: int, batch_total: int) -> str:
    plans = [proposal_plan(persona_id, index, spec, outcomes) for index in indices]
    first_name = spec["display_name"].split()[0]
    items = []
    for position, plan in enumerate(plans, start=1):
        if plan["generic_opener"]:
            opener = 'start with exactly "Dear Hiring Manager" (ignored proposal)'
        else:
            opener = ('open with "Hi" or "Hello" plus a specific detail from the job; '
                      'never write "Hiring Manager"')
        items.append(
            f"{position}. FILE: {plan_path(persona_id, plan)}\n"
            f"   Outcome label (do not mention it): {plan['outcome']}\n"
            f"   Category: {plan['category']} | Job title: {plan['job_title']} | "
            f"Budget: ${plan['budget']}\n"
            f"   Tone: {plan['tone']} | Length: {plan['length']}\n"
            f"   Opener: {opener}"
        )
    start, end = indices[0], indices[-1]
    first = plans[0]
    return f"""# Prompt pack: {persona_id} — past proposals {start:03d}-{end:03d}
# (batch {batch_no} of {batch_total})

You are writing past freelance cover letters for {spec['display_name']}, a
{persona_id} freelancer ({spec['headline']}). Sign off as {first_name} if you
sign off at all; never invent another name.

Write one cover-letter body per item below, as if sent for that job, without
mentioning the outcome label.

{PROPOSAL_RULES}

## Proposals in this batch

{chr(10).join(items)}

## Output format (strict)

Your reply MUST contain exactly {len(plans)} FILE blocks, one per item above, in
the same order. Each block starts with a line of the form
`=== FILE: <path from the item> ===` (the marker on its own line), followed by
the proposal body. Put each marker on its own line, outside any code fence.
Do not output a combined answer or prose outside the blocks.

The first block therefore looks like:

=== FILE: {plan_path(persona_id, first)} ===
<proposal body for item 1>
"""


# --------------------------------------------------------------- prompt packing


def emit_cv_reviews_prompt(persona_id: str, spec: dict, prompts_dir: Path,
                           reviews_count: int, force: bool) -> Path:
    path = prompts_dir / f"{persona_id}_cv_reviews.md"
    write_if_missing(path, build_cv_reviews_prompt(persona_id, spec, reviews_count), force)
    return path


def emit_case_studies_prompts(persona_id: str, spec: dict, prompts_dir: Path,
                              force: bool, limit: int) -> list[Path]:
    entries = list(enumerate(spec["case_studies"], start=1))[: max(0, limit)]
    batches = chunks(entries, CASE_STUDY_BATCH)
    paths = []
    for batch_no, batch in enumerate(batches, start=1):
        path = prompts_dir / f"{persona_id}_case_studies_{batch_no}of{len(batches)}.md"
        prompt = build_case_studies_prompt(persona_id, spec, batch, batch_no, len(batches))
        write_if_missing(path, prompt, force)
        paths.append(path)
    return paths


def emit_proposals_prompts(persona_id: str, spec: dict, outcomes: dict, prompts_dir: Path,
                           count: int, force: bool) -> list[Path]:
    indices = list(range(1, count + 1))
    batches = chunks(indices, PROPOSAL_BATCH)
    paths = []
    for batch_no, batch in enumerate(batches, start=1):
        start, end = batch[0], batch[-1]
        path = prompts_dir / f"{persona_id}_proposals_{start:03d}-{end:03d}.md"
        prompt = build_proposals_prompt(persona_id, spec, outcomes, batch,
                                        batch_no, len(batches))
        write_if_missing(path, prompt, force)
        paths.append(path)
    return paths


def emit_prompt_pack(persona_ids: list[str], outcomes: dict, personas_dir: Path,
                     proposal_count: int, case_studies_limit: int, reviews_count: int,
                     force: bool, dry_run: bool) -> int:
    prompts_dir = personas_dir / "_prompts"
    inbox_dir = personas_dir / "_inbox"
    total = 0
    for persona_id in persona_ids:
        spec = PERSONAS[persona_id]
        case_total = min(case_studies_limit, len(spec["case_studies"]))
        case_batches = (case_total + CASE_STUDY_BATCH - 1) // CASE_STUDY_BATCH
        proposal_batches = (proposal_count + PROPOSAL_BATCH - 1) // PROPOSAL_BATCH
        if dry_run:
            print(f"[{persona_id}] would write 1 CV+reviews prompt, {case_batches} "
                  f"case-study prompts, {proposal_batches} proposal prompts")
            total += 1 + case_batches + proposal_batches
            continue
        paths = [emit_cv_reviews_prompt(persona_id, spec, prompts_dir, reviews_count, force)]
        paths += emit_case_studies_prompts(persona_id, spec, prompts_dir, force,
                                           case_studies_limit)
        paths += emit_proposals_prompts(persona_id, spec, outcomes, prompts_dir,
                                        proposal_count, force)
        for path in paths:
            print(f"  {path.relative_to(personas_dir)}")
        total += len(paths)
    if dry_run:
        print(f"[dry-run] would write {total} prompt files, no files written")
        return 0
    inbox_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nWrote {total} prompt files.")
    print("Next steps:")
    print("  1. Open each prompt file and paste its entire contents into a free chat UI")
    print("     (ChatGPT / Gemini / Claude web).")
    print("  2. Copy the complete reply and save it as")
    try:
        inbox_display = inbox_dir.relative_to(REPO_ROOT)
    except ValueError:
        inbox_display = inbox_dir
    print(f"     {inbox_display}/<same-name>.txt")
    print("  3. Run: python data/scripts/generate_personas.py --import-inbox")
    return 0


# ------------------------------------------------------------------ import mode


def strip_frontmatter(body: str) -> str:
    match = re.match(r"^---\s*\n.*?\n---\s*\n?", body, re.DOTALL)
    return body[match.end():] if match else body


def apply_answer_text(text: str, personas_dir: Path, outcomes: dict, force: bool,
                      source: str) -> tuple[int, int]:
    """Parse '=== FILE: ... ===' blocks and write them under the personas dir."""
    matches = list(FILE_MARKER.finditer(text))
    if not matches:
        print(f"[import] {source}: no '=== FILE: ... ===' blocks found, skipping")
        return 0, 0
    written = skipped = 0
    root = personas_dir.resolve()
    for i, match in enumerate(matches):
        rel = match.group(1).strip().strip("`").strip()
        rel = rel.removeprefix("data/personas/")
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        target = (personas_dir / rel).resolve()
        if not target.is_relative_to(root):
            print(f"[import] {source}: rejected path outside personas dir: {rel}")
            skipped += 1
            continue
        if not body:
            skipped += 1
            continue
        proposal = PROPOSAL_PATH.match(rel)
        if proposal:
            persona_id = proposal.group("persona")
            spec = PERSONAS.get(persona_id)
            if spec is None:
                print(f"[import] {source}: unknown persona in {rel}, skipping")
                skipped += 1
                continue
            plan = proposal_plan(persona_id, int(proposal.group("index")), spec, outcomes)
            if plan["outcome"] != proposal.group("outcome"):
                print(f"[import] {source}: warning: {rel} label differs from plan; "
                      f"using plan outcome '{plan['outcome']}'")
            meta = {"outcome": plan["outcome"], "job_category": plan["category"],
                    "budget": plan["budget"], "date": plan["date"]}
            content = f"{frontmatter(meta)}\n\n{strip_frontmatter(body)}"
        else:
            content = body
        if write_if_missing(target, content, force):
            written += 1
        else:
            skipped += 1
    print(f"[import] {source}: {written} written, {skipped} skipped")
    return written, skipped


def import_answers(path: Path, personas_dir: Path, outcomes: dict, force: bool) -> tuple[int, int]:
    return apply_answer_text(path.read_text(), personas_dir, outcomes, force, path.name)


def import_inbox(personas_dir: Path, outcomes: dict, force: bool) -> int:
    inbox = personas_dir / "_inbox"
    if not inbox.exists():
        print(f"[import] inbox not found: {inbox} (run --emit-prompts first)")
        return 1
    answers = sorted(inbox.glob("*.txt"))
    if not answers:
        print(f"[import] no .txt answers in {inbox} — save chat replies there first")
        return 1
    total_written = total_skipped = 0
    for path in answers:
        written, skipped = import_answers(path, personas_dir, outcomes, force)
        total_written += written
        total_skipped += skipped
    print(f"[import] done: {total_written} files written, {total_skipped} skipped "
          f"from {len(answers)} answer file(s)")
    return 0


# ------------------------------------------------------------- direct generation


def _proposals_missing(persona_id: str, spec: dict, outcomes: dict, personas_dir: Path,
                       indices: list[int], force: bool) -> bool:
    if force:
        return True
    for index in indices:
        plan = proposal_plan(persona_id, index, spec, outcomes)
        if not (personas_dir / plan_path(persona_id, plan)).exists():
            return True
    return False


def _case_studies_missing(persona_id: str, spec: dict, personas_dir: Path,
                          entries: list[tuple[int, tuple[str, list[str]]]],
                          force: bool) -> bool:
    if force:
        return True
    return any(
        not (personas_dir / persona_id / case_study_filename(index, name)).exists()
        for index, (name, _skills) in entries
    )


def generate_persona(persona_id: str, spec: dict, personas_dir: Path, outcomes: dict,
                     args: argparse.Namespace) -> None:
    base = personas_dir / persona_id
    print(f"\n[{persona_id}] {spec['display_name']} — {spec['headline']}")
    write_skills_json(persona_id, spec, personas_dir, args.force)

    cv_path = base / "cv.md"
    reviews_path = base / "reviews.md"
    if args.force or not (cv_path.exists() and reviews_path.exists()):
        print("  cv + reviews: generating (1 call)")
        prompt = build_cv_reviews_prompt(persona_id, spec, args.reviews_count)
        content = chat(prompt, max_tokens=2600)
        if content:
            apply_answer_text(content, personas_dir, outcomes, args.force,
                              f"{persona_id} cv+reviews")
    else:
        print("  cv + reviews: exists, skipping")

    entries = list(enumerate(spec["case_studies"], start=1))[: max(0, args.case_studies_limit)]
    batches = chunks(entries, CASE_STUDY_BATCH)
    for batch_no, batch in enumerate(batches, start=1):
        if not _case_studies_missing(persona_id, spec, personas_dir, batch, args.force):
            print(f"  case studies {batch_no}/{len(batches)}: exists, skipping")
            continue
        print(f"  case studies {batch_no}/{len(batches)}: generating (1 call)")
        prompt = build_case_studies_prompt(persona_id, spec, batch, batch_no, len(batches))
        content = chat(prompt, max_tokens=4600)
        if content:
            apply_answer_text(content, personas_dir, outcomes, args.force,
                              f"{persona_id} case studies {batch_no}")

    indices = list(range(1, args.limit + 1))
    proposal_batches = chunks(indices, PROPOSAL_BATCH)
    for batch_no, batch in enumerate(proposal_batches, start=1):
        if not _proposals_missing(persona_id, spec, outcomes, personas_dir, batch, args.force):
            print(f"  proposals {batch_no}/{len(proposal_batches)}: exists, skipping")
            continue
        print(f"  proposals {batch_no}/{len(proposal_batches)}: generating (1 call)")
        prompt = build_proposals_prompt(persona_id, spec, outcomes, batch,
                                        batch_no, len(proposal_batches))
        content = chat(prompt, max_tokens=4600, temperature=0.5)
        if content:
            apply_answer_text(content, personas_dir, outcomes, args.force,
                              f"{persona_id} proposals {batch_no}")

    proposals = sorted((base / "proposals").glob("*.md")) if (base / "proposals").exists() else []
    studies = sorted((base / "case_studies").glob("*.md")) if (base / "case_studies").exists() else []
    reviews = reviews_path.read_text().strip().splitlines() if reviews_path.exists() else []
    print(f"  done: {len(proposals)} proposals, {len(studies)} case studies, "
          f"{len(reviews)} review lines")


def dry_run_persona(persona_id: str, spec: dict, personas_dir: Path, outcomes: dict,
                    args: argparse.Namespace) -> int:
    base = personas_dir / persona_id
    calls = 0
    if args.force or not ((base / "cv.md").exists() and (base / "reviews.md").exists()):
        calls += 1
    entries = list(enumerate(spec["case_studies"], start=1))[: max(0, args.case_studies_limit)]
    calls += sum(
        1 for batch in chunks(entries, CASE_STUDY_BATCH)
        if _case_studies_missing(persona_id, spec, personas_dir, batch, args.force)
    )
    indices = list(range(1, args.limit + 1))
    calls += sum(
        1 for batch in chunks(indices, PROPOSAL_BATCH)
        if _proposals_missing(persona_id, spec, outcomes, personas_dir, batch, args.force)
    )
    print(f"[{persona_id}] {calls} LLM calls "
          f"({args.limit} proposals, {len(entries)} case studies, {args.reviews_count} reviews)")
    return calls


# ------------------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--persona", choices=sorted(PERSONAS), help="generate only this persona")
    parser.add_argument("--limit", type=int, default=DEFAULT_PROPOSALS,
                        help=f"number of proposals per persona (default {DEFAULT_PROPOSALS})")
    parser.add_argument("--case-studies-limit", type=int, default=DEFAULT_CASE_STUDIES,
                        help=f"number of case studies per persona (default {DEFAULT_CASE_STUDIES})")
    parser.add_argument("--reviews-count", type=int, default=DEFAULT_REVIEWS,
                        help=f"number of client reviews (default {DEFAULT_REVIEWS})")
    parser.add_argument("--provider", choices=["auto", "ollama", "groq", "none"],
                        help="override DATA_LLM_PROVIDER for this run")
    parser.add_argument("--budget", type=int, help="prompt+completion token budget for this run")
    parser.add_argument("--force", action="store_true", help="overwrite existing files")
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would be generated without LLM calls")
    parser.add_argument("--emit-prompts", action="store_true",
                        help="write paste-ready prompts for free web chat UIs")
    parser.add_argument("--import", dest="import_path", metavar="FILE",
                        help="import a saved chat reply containing '=== FILE: ... ===' blocks")
    parser.add_argument("--import-inbox", action="store_true",
                        help="import every .txt answer file from data/personas/_inbox/")
    parser.add_argument("--out-dir", default=str(REPO_ROOT / "data" / "processed"),
                        help="processed data dir (reads outcomes.json)")
    parser.add_argument("--personas-dir", default=str(REPO_ROOT / "data" / "personas"))
    args = parser.parse_args()

    load_env_file()
    if args.provider:
        os.environ["DATA_LLM_PROVIDER"] = args.provider
    if args.budget:
        os.environ["LLM_TOKEN_BUDGET"] = str(args.budget)
    provider(force=True)

    personas_dir = Path(args.personas_dir)
    outcomes = load_outcomes(Path(args.out_dir))
    selected = [args.persona] if args.persona else sorted(PERSONAS)

    if args.import_path:
        written, skipped = import_answers(Path(args.import_path), personas_dir, outcomes,
                                          args.force)
        return 0 if (written + skipped) else 1
    if args.import_inbox:
        return import_inbox(personas_dir, outcomes, args.force)

    if args.emit_prompts:
        return emit_prompt_pack(selected, outcomes, personas_dir, args.limit,
                                args.case_studies_limit, args.reviews_count,
                                args.force, args.dry_run)

    active = provider()
    if active == "none":
        print("error: no LLM provider available. Options:")
        print("  - start Ollama locally (ollama serve) and set OLLAMA_MODEL if needed")
        print("  - set GROQ_API_KEY in .env and pass --provider groq")
        print("  - use --emit-prompts to generate prompts for a free web chat UI")
        return 1

    if args.dry_run:
        total = sum(dry_run_persona(pid, PERSONAS[pid], personas_dir, outcomes, args)
                    for pid in selected)
        print(f"[dry-run] {total} LLM calls, no files written")
        return 0

    print(f"[llm] using {describe()}")
    try:
        for persona_id in selected:
            generate_persona(persona_id, PERSONAS[persona_id], personas_dir, outcomes, args)
    except QuotaExhausted as exc:
        print(f"\n[quota] {exc}")
        print(f"[quota] usage: {usage_summary()}")
        print("[quota] finished files are on disk; rerun the same command to resume")
        return 2

    print(f"\n[done] persona corpora complete — {usage_summary()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
