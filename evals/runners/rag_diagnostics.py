"""Explain recorded failures and simulator gates without changing outcomes."""

from collections import Counter


def reply_diagnostics(case: dict, draft: str, status: str) -> dict:
    """Mirror GigSim's ordered gates for analysis, never for choosing an outcome."""
    client, job = case["client"], case["job"]
    cover = draft.lower()
    mentioned = {s.lower() for s in job["skills"] if s.lower() in cover}
    required = {
        s.lower() for s in client["hidden_preferences"].get("must_have_skills", [])
    }
    gate = (
        "low_hire_rate"
        if client["hire_rate"] < 0.1
        else "skill_mismatch"
        if required and not required & mentioned
        else "generic_opener"
        if "dear hiring manager" in cover
        else "eligible"
    )
    reason = (
        gate
        if gate != "eligible"
        else "eligible_no_reply"
        if status == "no_reply"
        else status
    )
    return {
        "gate": gate,
        "reason": reason,
        "mentioned_job_skills": sorted(mentioned),
        "matching_skill_count": len(required & mentioned),
    }


def failure_diagnostics(rows: list[dict], cases: dict | None = None) -> dict:
    codes, categories, verifier, gates, reasons = (Counter() for _ in range(5))
    for row in rows:
        error = row.get("error")
        if error:
            code = error["code"]
            codes[code] += 1
            category = (
                "embedding"
                if code.startswith("embedding_")
                else "decomposition"
                if "requirement" in error.get("message", "").lower()
                else "structured_model"
                if code.startswith("model_")
                else code
            )
            categories[category] += 1
        for failure in (
            row.get("verification", {}).get("diagnostics", {}).get("failures", [])
        ):
            verifier[failure["message"]] += 1
        outcome = row.get("outcome") or {}
        if outcome.get("submitted"):
            details = outcome
            if "gate" not in details and cases and row["id"] in cases:
                details = reply_diagnostics(
                    cases[row["id"]], row["cleaned_draft"], outcome["status"]
                )
            gates[details.get("gate", "not_recorded")] += 1
            reasons[details.get("reason", "not_recorded")] += 1
    return {
        "failure_codes": dict(codes),
        "failure_categories": dict(categories),
        "verification_failure_count": sum(verifier.values()),
        "verification_failure_reasons": dict(verifier),
        "assessment_failures": sum(bool(row.get("assessment_error")) for row in rows),
        "reply_gate_counts": dict(gates),
        "reply_reason_counts": dict(reasons),
    }
