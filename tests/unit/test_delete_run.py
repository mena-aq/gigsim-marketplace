"""Run deletion must refuse in-flight and sent runs."""

from apps.api.orchestration import UNDELETABLE


def test_only_finished_unsent_runs_can_be_deleted():
    assert {"queued", "running", "sent"} == UNDELETABLE
    for status in ("needs_attention", "awaiting_approval", "rejected", "skip"):
        assert status not in UNDELETABLE
