"""V2: BM25 and dense candidates combined with reciprocal rank fusion."""

from rag.ranking import bm25, fuse


async def retrieve(query: str, context, k: int):
    dense = await context.dense(query, k)
    lexical = bm25(query, context.filtered_chunks, k)
    return fuse([dense, lexical], context.config.rrf_constant, k)
