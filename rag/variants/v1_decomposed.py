"""V1: source-anchored requirement decomposition and fused dense searches."""

import re

from rag.ranking import fuse
from rag.types import RagFailure, Requirements


async def retrieve(query: str, context, k: int):
    result = await context.llm.ask("rag_decompose", {"query": query}, Requirements)
    normalized = re.sub(r"\s+", " ", query.casefold())
    requirements = []
    for item in result.items:
        if not item.strip() or re.sub(r"\s+", " ", item.casefold()) not in normalized:
            raise RagFailure(
                "model_response_invalid",
                "A decomposed requirement was not anchored in the source query",
            )
        if item not in requirements:
            requirements.append(item)
    requirements = requirements[: context.config.max_requirements]
    context.diagnostics["requirements"] = requirements
    rankings = [await context.dense(requirement, k) for requirement in requirements]
    return fuse(rankings, context.config.rrf_constant, k)
