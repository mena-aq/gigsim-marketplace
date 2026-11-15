"""Generate B3/B5 and calibrate one overall quality score against human labels."""

import csv
import hashlib
import json
import random
from pathlib import Path
from statistics import mean

from rag.config import VARIANTS

RUBRIC = (
    "Give ONE integer score (1–5), considering relevance, specificity, grounding and clarity together. "
    "1: irrelevant/fabricated; 2: weak/vague/unsupported; 3: adequate; "
    "4: clear, relevant and grounded; 5: excellent fit with compelling evidence and approach."
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def agreement(human: list[int], judge: list[int]) -> dict:
    """Compute unweighted Cohen's kappa and exact agreement for ordinal scores."""
    if (
        not human
        or len(human) != len(judge)
        or any(type(s) is not int or not 1 <= s <= 5 for s in human + judge)
    ):
        raise ValueError("Equal nonempty lists of integer scores from 1 to 5 required")
    observed = mean(a == b for a, b in zip(human, judge, strict=True))
    expected = (
        sum(human.count(s) * judge.count(s) for s in range(1, 6)) / len(human) ** 2
    )
    return {
        "items": len(human),
        "exact_agreement": observed,
        "cohens_kappa": (observed - expected) / (1 - expected)
        if expected < 1
        else None,
    }


def review_pack(folder: Path) -> dict:
    """Freeze a blinded pack; never overwrite user labels or its private key."""
    pack = folder / "rag_human_review.csv"
    if pack.exists():
        return {"status": "existing", "path": str(pack)}
    rows = [
        json.loads(line)
        for line in (folder / "rag_workflow_observations.jsonl")
        .read_text()
        .splitlines()
    ]
    rng = random.Random(42)
    selected = []
    personas = sorted({r["persona"] for r in rows})
    eligible = [r for r in rows if r.get("judge_score_uncalibrated") is not None]
    deficits = {
        variant: 6 - sum(r["variant"] == variant for r in eligible)
        for variant in VARIANTS
        if sum(r["variant"] == variant for r in eligible) < 6
    }
    if len(personas) != 3 or deficits:
        return {
            "status": "pending",
            "reason": "Need three personas and six judge-scored proposals per variant",
            "deficits": deficits,
        }
    for variant in VARIANTS:
        arm = [r for r in eligible if r["variant"] == variant]
        chosen = []
        # Aim for two per persona, then fill sparse cells from the same variant.
        for persona in personas:
            cell = [r for r in arm if r["persona"] == persona]
            chosen.extend(rng.sample(cell, min(2, len(cell))))
        remaining = [r for r in arm if r not in chosen]
        rng.shuffle(remaining)
        while len(chosen) < 6:
            next_row = min(
                remaining,
                key=lambda r: sum(c["persona"] == r["persona"] for c in chosen),
            )
            chosen.append(next_row)
            remaining.remove(next_row)
        selected.extend(chosen)
    rng.shuffle(selected)
    dataset = json.loads((folder / "rag_jobs.json").read_text())
    jobs = {c["id"]: c["job"] for c in dataset["cases"]}
    key = []
    with pack.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["review_id", "job", "proposal", "evidence", "human_score"],
        )
        writer.writeheader()
        for i, row in enumerate(selected):
            review_id = f"P{i + 1:02d}"
            writer.writerow(
                {
                    "review_id": review_id,
                    "job": jobs[row["id"]]["title"]
                    + "\n"
                    + jobs[row["id"]]["description"],
                    "proposal": row["cleaned_draft"],
                    "evidence": "\n\n".join(
                        h["chunk"]["text"] for h in row["retrieval"]["hits"]
                    ),
                    "human_score": "",
                }
            )
            key.append(
                {
                    "review_id": review_id,
                    "id": row["id"],
                    "variant": row["variant"],
                    "judge_score": row["judge_score_uncalibrated"],
                    "fingerprint": row["fingerprint"],
                }
            )
    (folder / "rag_calibration_key.json").write_text(json.dumps(key, indent=2) + "\n")
    (folder / "rag_human_review.md").write_text(
        "# Human review\n\n"
        + RUBRIC
        + "\n\nFill only human_score in rag_human_review.csv. "
        "Do not inspect rag_calibration_key.json before scoring. No comments or sub-scores required.\n\n"
        "Sampling: six scored proposals per variant, aiming for two per persona. Sparse cells "
        "are filled from other personas within the same variant. This pack represents "
        "judge-scored outputs; failed and empty outputs are excluded.\n"
    )
    return {"status": "created", "path": str(pack), "items": len(selected)}


def calibrate(folder: Path) -> dict:
    """Import actual human scores and report agreement alongside judge means."""
    key = json.loads((folder / "rag_calibration_key.json").read_text())
    with (folder / "rag_human_review.csv").open(newline="") as handle:
        labels = list(csv.DictReader(handle))
    if (
        len(labels) != 30
        or len(key) != 30
        or len({r["review_id"] for r in labels}) != 30
    ):
        raise ValueError("Exactly 30 unique human-scored items required")
    keyed = {r["review_id"]: r for r in key}
    if set(keyed) != {r["review_id"] for r in labels}:
        raise ValueError("Review IDs differ from the frozen pack")
    rows = [
        json.loads(line)
        for line in (folder / "rag_workflow_observations.jsonl")
        .read_text()
        .splitlines()
    ]
    observations = {(r["id"], r["variant"]): r for r in rows}
    dataset = json.loads((folder / "rag_jobs.json").read_text())
    jobs = {c["id"]: c["job"] for c in dataset["cases"]}
    human, judge, pairs = [], [], []
    for label in labels:
        item = keyed[label["review_id"]]
        row = observations[(item["id"], item["variant"])]
        if (
            row["fingerprint"] != item["fingerprint"]
            or row["judge_score_uncalibrated"] != item["judge_score"]
        ):
            raise ValueError("Calibration key does not match measured observations")
        job = jobs[row["id"]]
        evidence = "\n\n".join(h["chunk"]["text"] for h in row["retrieval"]["hits"])
        if (
            label["proposal"] != row["cleaned_draft"]
            or label["evidence"] != evidence
            or label["job"] != job["title"] + "\n" + job["description"]
        ):
            raise ValueError("Review text was edited; change only human_score")
        try:
            score = int(label["human_score"])
        except (ValueError, TypeError):
            raise ValueError(
                "Fill all 30 human_score cells with integers 1–5"
            ) from None
        human.append(score)
        judge.append(item["judge_score"])
        pairs.append({**item, "human_score": score})
    result = agreement(human, judge)
    result.update(
        {
            "minimum_kappa": 0.4,
            "status": "calibrated"
            if result["cohens_kappa"] is not None and result["cohens_kappa"] >= 0.4
            else "insufficient_agreement",
            "pairs": pairs,
            "observations_sha256": digest(folder / "rag_workflow_observations.jsonl"),
            "human_review_sha256": digest(folder / "rag_human_review.csv"),
            "limitation": "Same local model for generation and judging; shared bias remains possible",
        }
    )
    (folder / "rag_judge_calibration.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
    return result
