"""Checkpointed working state; audit and promoted memory live separately."""

import operator
from typing import Annotated, TypedDict


def merge(left: dict, right: dict) -> dict:
    return {**left, **right}


class GigBidState(TypedDict, total=False):
    user_id: str
    thread_id: str
    turn_id: str
    trace_id: str
    job_id: str
    conversation_id: str
    job: dict
    analyses: Annotated[dict, merge]
    evidence: list[dict]
    decision: dict
    price: dict
    draft: dict
    verification: dict
    verification_failed: bool
    critique: dict
    revisions: int
    compliance: dict
    policy_hash: str
    preview: dict
    request: dict
    approval: dict
    result: dict
    messages: list[dict]
    intent: dict
    slots: dict
    style: list[dict]
    outcomes: list[dict]
    edits: list[dict]
    status: str
    steps: Annotated[int, operator.add]
    tokens: Annotated[int, operator.add]
    errors: Annotated[dict, merge]
