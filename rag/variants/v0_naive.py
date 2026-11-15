"""V0: fixed chunks, whole-query dense cosine ranking."""


async def retrieve(query: str, context, k: int):
    return await context.dense(query, k)
