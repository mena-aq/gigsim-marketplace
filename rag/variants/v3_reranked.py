"""V3: a CPU cross-encoder reranks the hybrid candidate pool."""

import asyncio

from rag.types import Hit
from rag.variants.v2_hybrid import retrieve as hybrid


async def retrieve(query: str, context, k: int):
    candidates = await hybrid(query, context, k)
    if not candidates:
        return []
    scores = await asyncio.to_thread(
        context.rerank, query, [hit.chunk.text for hit in candidates]
    )
    context.diagnostics["reranked_pairs"] = context.diagnostics.get(
        "reranked_pairs", 0
    ) + len(candidates)
    return sorted(
        [
            Hit(chunk=hit.chunk, score=score)
            for hit, score in zip(candidates, scores, strict=True)
        ],
        key=lambda hit: (-hit.score, hit.chunk.chunk_id),
    )
