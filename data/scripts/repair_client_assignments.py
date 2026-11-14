"""Repair processed client assignments and freeze a new benchmark, without LLMs."""

import argparse
import copy
import hashlib
import json
import random
from pathlib import Path

from data.client_matching import assign_clients, ensure_client_coverage
from data.scripts.process import BAD_ACTOR_RATE, build_outcomes, finish_clients

ROOT = Path(__file__).resolve().parents[2]


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path: Path, value) -> None:
    """Permit identical reruns, but never replace a different dataset version."""
    content = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()
    if path.exists() and path.read_bytes() != content:
        raise ValueError(
            f"Different data already exists at {path}; choose a new destination"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def repair(
    source: Path, output: Path, benchmark: Path, snapshot: Path, seed: int = 42
) -> dict:
    """Reuse original public jobs and profiles, adding coverage only where absent."""
    if (
        source.resolve() == output.resolve()
        or snapshot.resolve() == benchmark.resolve()
    ):
        raise ValueError("Repair requires new output paths; preserve original data")
    names = ("jobs.json", "stream_jobs.json", "clients.json")
    originals = {name: json.loads((source / name).read_text()) for name in names}
    hashes = {name: file_hash(source / name) for name in names}
    jobs, stream, clients = (copy.deepcopy(originals[name]) for name in names)
    all_jobs = jobs + stream
    added = ensure_client_coverage(all_jobs, clients, seed)
    rng = random.Random(seed)
    for client in added:
        client["is_bad_actor"] = False
    extra_bad = max(
        0,
        round(BAD_ACTOR_RATE * len(clients))
        - sum(c.get("is_bad_actor", False) for c in clients),
    )
    for client in rng.sample(added, min(extra_bad, len(added))):
        client.update(
            is_bad_actor=True,
            hire_rate=round(rng.uniform(0.01, 0.08), 2),
            payment_verified=False,
        )
    finish_clients(added, {}, rng)
    report = assign_clients(all_jobs, clients, seed)
    report.update(
        seed=seed,
        added_clients=len(added),
        source_hashes=hashes,
        existing_profiles_preserved=True,
    )
    by_job = {j["id"]: j for j in all_jobs}
    by_client = {c["id"]: c for c in clients}
    old_jobs = {
        j["id"]: j for j in originals["jobs.json"] + originals["stream_jobs.json"]
    }
    previous = json.loads(benchmark.read_text())
    updated = copy.deepcopy(previous)
    for case in updated["cases"]:
        job = case["job"]
        original = old_jobs.get(case["id"])
        if original is None or any(
            original.get(k) != v for k, v in job.items() if k != "client_id"
        ):
            raise ValueError(
                "Benchmark public jobs differ from source; review rather than resample"
            )
        job["client_id"] = by_job[case["id"]]["client_id"]
        case["client"] = by_client[job["client_id"]]
    updated.update(
        version=2,
        repair={
            **report,
            "original_benchmark_sha256": file_hash(benchmark),
            "policy": "Same public jobs; seeded skill-compatible clients; no reply observations used",
        },
    )
    for name, value in zip(names, (jobs, stream, clients), strict=True):
        write_new(output / name, value)
    write_new(output / "outcomes.json", build_outcomes(clients, all_jobs))
    updated["source_jobs_sha256"] = file_hash(output / "jobs.json")
    updated["source_clients_sha256"] = file_hash(output / "clients.json")
    write_new(output / "client_assignment_report.json", report)
    write_new(snapshot, updated)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "data/processed")
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "data/processed/repaired_clients"
    )
    parser.add_argument(
        "--benchmark", type=Path, default=ROOT / "evals/datasets/rag_jobs.json"
    )
    parser.add_argument(
        "--snapshot", type=Path, default=ROOT / "evals/datasets/rag_jobs_v2.json"
    )
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                repair(
                    args.source,
                    args.output_dir,
                    args.benchmark,
                    args.snapshot,
                    args.seed,
                )
            )
        )
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Client repair stopped: {exc}\n")


if __name__ == "__main__":
    main()
