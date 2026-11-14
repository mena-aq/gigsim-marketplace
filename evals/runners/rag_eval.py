"""One Part B evaluation: retrieval, B3 verification, B5 metrics, and ablation."""

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from evals.runners import rag_ablation, rag_retrieval, rag_workflow
from evals.runners.rag_calibration import review_pack
from evals.runners.rag_environment import capture_environment
from evals.runners.rag_metrics import aggregate, code_fingerprint, metrics, percentile
from evals.runners.rag_preflight import preflight
from rag.config import ROOT, VARIANTS, load_config
from rag.types import RagFailure

__all__ = ["aggregate", "code_fingerprint", "metrics", "percentile"]
RESULTS = ROOT / "evals/results"


def run_fingerprint(args) -> str:
    """Bind resumable stages to the same code, configuration, and fixtures."""
    paths = sorted((ROOT / "evals/runners").glob("rag*.py"))
    paths += sorted((ROOT / "rag").rglob("*.py"))
    paths += sorted((ROOT / "mcp_servers").rglob("*.py"))
    paths += sorted((ROOT / "gigsim").rglob("*.py"))
    paths += [ROOT / "data/client_matching.py"]
    paths += sorted((ROOT / "agent/prompts").glob("rag*.md"))
    config = load_config()
    paths += sorted((config.data_dir / "indexes").glob("*.json"))
    paths += [config.data_dir / "models/manifest.json"]
    paths += [
        ROOT / "agent/config.yaml",
        ROOT / "uv.lock",
        args.retrieval_dataset,
        args.jobs_dataset,
        args.claim_dataset,
    ]
    body = {
        "files": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        "config": config.model_dump(mode="json"),
        "limit": args.limit,
        "variants": args.variants,
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


async def run(args) -> None:
    """Execute all benchmark stages; completed observations are resumable."""
    from evals.runners.rag_table import write_report

    folder = args.output_dir
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "rag_run.json"
    fingerprint = run_fingerprint(args)
    manifest = (
        json.loads(path.read_text())
        if path.exists()
        else {
            "fingerprint": fingerprint,
            "stages": [],
            "limit": args.limit,
            "variants": args.variants,
            "workflow": "rag_benchmark",
        }
    )
    if manifest["fingerprint"] != fingerprint:
        raise ValueError(
            "Cannot resume: code/configuration/fixtures changed; use a new --output-dir"
        )
    environment = folder / "rag_environment.json"
    await capture_environment(load_config(), environment, fingerprint)
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    print("RAG preflight: embedding boundary and simulator controls", flush=True)
    checks = await preflight(load_config(), args.jobs_dataset)
    (folder / "rag_preflight.json").write_text(json.dumps(checks, indent=2) + "\n")
    stages = (
        ("retrieval_and_claim_regressions", rag_retrieval.run, args),
        ("draft_verify_assess_judge_outcomes", rag_workflow.run, args),
        (
            "ablation",
            rag_ablation.main_async,
            SimpleNamespace(
                dataset=args.retrieval_dataset,
                output_dir=folder,
                claim_dataset=getattr(
                    args, "claim_dataset", ROOT / "evals/datasets/claim_dev.json"
                ),
            ),
        ),
    )
    for name, execute, stage_args in stages:
        if name in manifest["stages"]:
            continue
        print(f"RAG evaluation stage: {name}", flush=True)
        if name == "ablation" and args.limit:
            dataset = json.loads(args.retrieval_dataset.read_text())
            dataset["queries"] = dataset["queries"][: args.limit]
            subset = folder / "rag_ablation_input.json"
            subset.write_text(json.dumps(dataset, indent=2) + "\n")
            stage_args.dataset = subset
        await execute(stage_args)
        if run_fingerprint(args) != fingerprint:
            raise ValueError(
                "Code/configuration/fixtures/indexes changed during evaluation"
            )
        await capture_environment(load_config(), environment, fingerprint)
        manifest["stages"].append(name)
        path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"review_pack": review_pack(folder)}), flush=True)
    full = not args.limit and set(args.variants) == set(VARIANTS)
    write_report(folder, publish=full, update_readme=full)
    print(f"RAG evaluation saved: {folder / 'rag_comparison.csv'}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--resume", type=Path, help="Resume an existing unified run directory"
    )
    parser.add_argument(
        "--retrieval-dataset", type=Path, default=ROOT / "evals/datasets/rag_dev.json"
    )
    parser.add_argument(
        "--jobs-dataset", type=Path, default=ROOT / "evals/datasets/rag_jobs_v2.json"
    )
    parser.add_argument(
        "--claim-dataset", type=Path, default=ROOT / "evals/datasets/claim_dev.json"
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--variants", nargs="+", choices=VARIANTS, default=list(VARIANTS)
    )
    args = parser.parse_args()
    if args.limit < 0 or len(set(args.variants)) != len(args.variants):
        parser.error("Limit must be nonnegative and variants unique")
    if args.resume and args.output_dir:
        parser.error("Use --resume or --output-dir, not both")
    if args.resume and not (args.resume / "rag_run.json").exists():
        parser.error("--resume requires a unified run with rag_run.json")
    args.output_dir = (
        args.resume
        or args.output_dir
        or RESULTS / "runs" / datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    ).resolve()
    try:
        asyncio.run(run(args))
    except (OSError, ValueError, RagFailure) as exc:
        parser.exit(1, f"RAG evaluation stopped: {exc}\n")


if __name__ == "__main__":
    main()
