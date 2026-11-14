"""R&D question C (reduced): single ReAct-style agent (a) vs the hand-built graph (c).

    uv run python -m evals.runners.agent_compare --limit 2          # smoke test
    uv run python -m evals.runners.agent_compare                    # 20 jobs, both arms
    uv run python -m evals.runners.agent_compare --resume <run dir> # continue a run
    uv run python -m evals.runners.agent_compare --summarize <run dir>

One JSONL row per (arm, job) is appended as soon as it finishes, so a crash or Ctrl+C
loses at most the job in flight. Nothing is submitted to GigSim and no Connects are
spent: arm (c) stops before the graph's preview step, arm (a) has no write tools.
"""

import argparse
import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from agent.baselines.single_agent import run_single_agent
from agent.config import load_graph_config
from agent.execution import GraphServices, NodeContext
from agent.graphs.bid_graph import build_bid_graph
from evals.runners.agent_compare_metrics import (
    build_job_set,
    render_markdown,
    summarize,
)
from evals.runners.rag_workflow import claim_counts
from mcp_servers.common.errors import ToolFailure
from rag.config import ROOT

RESULTS = ROOT / "evals/results/agent_compare"
JOB_TIMEOUT_SECONDS = 45 * 60


def load_cases(seed: int) -> list[dict]:
    jobs = json.loads((ROOT / "data/processed/jobs.json").read_text())
    clients = json.loads((ROOT / "data/processed/clients.json").read_text())
    dev = json.loads((ROOT / "evals/datasets/proposal_dev.json").read_text())["cases"]
    return build_job_set(jobs, clients, dev, seed=seed)


def services_for(persona: str, config: dict) -> GraphServices:
    token = os.environ.get("MCP_TOKEN_" + persona.upper(), "")
    if not token:
        raise SystemExit(f"MCP_TOKEN_{persona.upper()} is not set (see .env)")
    return GraphServices(token=token, config=config, store=InMemoryStore())


async def verify_letter(services, case, letter: str, evidence_ids: list[str]) -> dict:
    """Run the portfolio verifier on a letter, as the graph's Verify node does."""
    ctx = NodeContext(services, {"user_id": "eval", "trace_id": "agent-compare"})
    report = await ctx.tool(
        "verifier",
        "verify_claims",
        {
            "request": {
                "draft": letter,
                "chunk_ids": evidence_ids[:20],
                "mode": "proposal",
            }
        },
    )
    return claim_counts(report)


async def arm_a(case: dict, config: dict) -> dict:
    services = services_for(case["persona"], config)
    result = await run_single_agent(
        services, case["id"], trace_id=f"cmp-a-{case['id']}"
    )
    row = {
        "action": result["action"],
        "reason": result["reason"],
        "cover_letter": result["cover_letter"],
        "submitted": result["action"] == "bid",  # no compliance gate in arm (a)
        "tokens": result["tokens"],
        "steps": len(result["trace"]),
        "trace": result["trace"],
    }
    if row["submitted"]:
        ids = [item["chunk_id"] for item in result["evidence"]]
        try:
            row["unsupported"] = await verify_letter(
                services, case, result["cover_letter"], ids
            )
        except (ToolFailure, ValueError) as exc:
            row["unsupported"] = None
            row["verify_error"] = str(exc)[:200]
    return row


async def arm_c(case: dict, config: dict) -> dict:
    services = services_for(case["persona"], config)
    graph = build_bid_graph(
        services,
        checkpointer=InMemorySaver(),
        store=services.store,
        interrupt_before=["preview"],  # never reach the marketplace dry run or approval
    )
    thread = {
        "configurable": {"thread_id": f"cmp-c-{case['id']}"},
        "recursion_limit": 100,
    }
    await graph.ainvoke(
        {
            "user_id": "eval",
            "thread_id": f"cmp-c-{case['id']}",
            "trace_id": f"cmp-c-{case['id']}",
            "turn_id": "initial",
            "job_id": case["id"],
            "steps": 0,
            "tokens": 0,
            "errors": {},
            "analyses": {},
            "edits": [],
        },
        thread,
    )
    snapshot = await graph.aget_state(thread)
    values = snapshot.values
    errors = values.get("errors") or {}
    decision = values.get("decision") or {}
    draft = values.get("draft") or {}
    reached_preview = tuple(snapshot.next) == ("preview",)
    row = {
        "action": decision.get("action"),
        "reason": decision.get("reason"),
        "cover_letter": draft.get("cover_letter", "")
        if decision.get("action") == "bid"
        else "",
        "submitted": reached_preview,  # compliance passed; would go to human review
        "tokens": values.get("tokens", 0),
        "revisions": values.get("revisions", 0),
        "status": values.get("status"),
        "caught_violations": len(
            (values.get("compliance") or {}).get("violations", [])
        ),
    }
    if errors:
        code, error = next(iter(errors.items()))
        row["error"] = f"{code}: {error.get('code')}"
    report = (values.get("verification") or {}).get("cover_letter")
    if report:
        try:
            row["unsupported"] = claim_counts(report)
        except ValueError:
            row["unsupported"] = None
    return row


ARMS = {"a": arm_a, "c": arm_c}


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_summary(
    folder: Path, cases: list[dict], manifest: dict, config: dict
) -> None:
    by_id = {case["id"]: case for case in cases}
    rows = read_rows(folder / "rows.jsonl")
    summaries = {
        arm: summarize([r for r in rows if r["arm"] == arm], by_id, config)
        for arm in ARMS
        if any(r["arm"] == arm for r in rows)
    }
    (folder / "agent_compare.json").write_text(json.dumps(summaries, indent=2) + "\n")
    (folder / "agent_compare.md").write_text(render_markdown(summaries, manifest))
    print((folder / "agent_compare.md").read_text())


async def main(args) -> None:
    config = load_graph_config()
    folder = args.resume or args.summarize or args.output_dir
    if folder is None:
        folder = RESULTS / datetime.now().strftime("%Y%m%d_%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    manifest_path = folder / "manifest.json"
    seed = (
        json.loads(manifest_path.read_text())["seed"]
        if manifest_path.exists()
        else args.seed
    )
    cases = load_cases(seed)
    kinds = [c["kind"] for c in cases]
    manifest = {
        "seed": seed,
        "jobs": len(cases),
        "mix": ", ".join(
            f"{kinds.count(k)} {k}" for k in ("clean", "scam", "injection")
        ),
        "ids": [c["id"] for c in cases],
    }
    if (
        manifest_path.exists()
        and json.loads(manifest_path.read_text())["ids"] != manifest["ids"]
    ):
        raise SystemExit(
            "Job set changed since this run started; use a new --output-dir"
        )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    if args.summarize:
        write_summary(folder, cases, manifest, config)
        return
    todo = cases[: args.limit] if args.limit else cases
    rows_path = folder / "rows.jsonl"
    for arm in args.arms:
        for case in todo:
            if any(
                r["arm"] == arm and r["id"] == case["id"] for r in read_rows(rows_path)
            ):
                continue
            print(
                f"[agent-compare] arm {arm} {case['kind']:<9} {case['persona']:<13} {case['id']}",
                flush=True,
            )
            start = time.perf_counter()
            try:
                async with asyncio.timeout(JOB_TIMEOUT_SECONDS):
                    row = await ARMS[arm](case, config)
            except (ToolFailure, TimeoutError, Exception) as exc:  # noqa: BLE001 - one job must not stop the run
                row = {
                    "action": None,
                    "submitted": False,
                    "error": f"{type(exc).__name__}: {exc}"[:300],
                }
            row.update(
                arm=arm,
                id=case["id"],
                persona=case["persona"],
                kind=case["kind"],
                gold=case["gold"],
                seconds=time.perf_counter() - start,
            )
            with rows_path.open("a") as handle:
                handle.write(json.dumps(row) + "\n")
            print(
                f"   -> {row.get('action')} in {row['seconds']:.0f}s {row.get('error') or ''}",
                flush=True,
            )
    write_summary(folder, cases, manifest, config)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--resume", type=Path, help="Continue an existing run folder")
    parser.add_argument(
        "--summarize", type=Path, help="Rebuild the table from rows.jsonl"
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="Only the first N jobs (mixed kinds)"
    )
    parser.add_argument("--arms", nargs="+", choices=sorted(ARMS), default=["a", "c"])
    parser.add_argument("--seed", type=int, default=0)
    parsed = parser.parse_args()
    if sum(bool(x) for x in (parsed.resume, parsed.summarize, parsed.output_dir)) > 1:
        parser.error("Use only one of --resume, --summarize, --output-dir")
    asyncio.run(main(parsed))
