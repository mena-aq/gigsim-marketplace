"""V1: choose source segments by ID, then fuse their dense rankings."""

from rag.ranking import fuse
from rag.types import RagFailure, RequirementSelection
from rag.verify import sentence_spans


async def retrieve(query: str, context, k: int):
    segments = {
        f"R{i + 1}": query[start:end]
        for i, (start, end) in enumerate(sentence_spans(query))
    }
    if not segments:
        raise RagFailure(
            "model_response_invalid", "Query has no selectable requirements"
        )
    result = await context.llm.ask(
        "rag_decompose",
        {"segments": [{"id": key, "text": value} for key, value in segments.items()]},
        RequirementSelection,
    )
    if any(key not in segments for key in result.ids):
        raise RagFailure(
            "model_response_invalid",
            "Selected requirement ID is not anchored in the source query",
        )
    selected = list(dict.fromkeys(result.ids))[: context.config.max_requirements]
    requirements = [segments[key] for key in selected]
    context.diagnostics.update(requirement_ids=selected, requirements=requirements)
    rankings = [await context.dense(requirement, k) for requirement in requirements]
    return fuse(rankings, context.config.rrf_constant, k)
