"""Explicit promotions into tenant-scoped LangGraph style and outcome stores."""

import difflib
import re

from agent.memory.promotion_rules import should_promote_style_edit
from mcp_servers.common.security import fingerprint, mask


async def promote_edits(store, state):
    if state.get("status") != "sent":
        return
    # Only exact whole sentences removed by the user are a supported style pattern.
    for edit in state.get("edits", []):
        old = re.split(r"(?<=[.!?])\s+", edit["before"]["cover_letter"])
        new = re.split(r"(?<=[.!?])\s+", edit["after"]["cover_letter"])
        for line in difflib.ndiff(old, new):
            if not line.startswith("- "):
                continue
            sentence = line[2:].strip()
            if not sentence or mask(sentence) != sentence:
                continue
            key = fingerprint({"removed_sentence": sentence})
            namespace = (state["user_id"], "style_observations")
            # One observation per distinct graph thread; retry-safe.
            await store.aput(
                namespace,
                key + ":" + state["thread_id"],
                {
                    "pattern": key,
                    "removed_sentence": sentence,
                    "thread_id": state["thread_id"],
                },
            )
            observations = await store.asearch(
                namespace, filter={"pattern": key}, limit=1000
            )
            if should_promote_style_edit(
                len({item.value["thread_id"] for item in observations}), True
            ):
                await store.aput(
                    (state["user_id"], "style"),
                    key,
                    {
                        "avoid_sentence": sentence,
                        "rule": "exact deletion in at least 3 approved threads",
                        "count": len(observations),
                    },
                )


async def promote_outcome(store, user_id, run_id, category, outcome, evidence):
    if outcome not in {"replied", "interview", "hired", "no_reply"}:
        return False
    if not evidence.get("confirmed"):
        return False
    await store.aput(
        (user_id, "outcome"),
        run_id,
        {
            "run_id": run_id,
            "category": category,
            "outcome": outcome,
            "source": "marketplace_client_history",
            "rule": "confirmed terminal marketplace status",
        },
    )
    return True
