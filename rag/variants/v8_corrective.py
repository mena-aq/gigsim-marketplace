"""V8: a real StateGraph with one bounded corrective retrieval."""

import re
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from rag.ranking import unique_items
from rag.types import Grade, Hit, RagFailure
from rag.variants.v3_reranked import retrieve as reranked


class CorrectiveState(TypedDict, total=False):
    query: str
    hits: list[Hit]
    grade: Grade
    corrections: int


async def retrieve(query: str, context, k: int):
    async def search(state):
        hits = await reranked(state["query"], context, k)
        return {"hits": unique_items(hits, context.config.grade_candidates)}

    async def grade(state):
        hits = state["hits"]
        if not hits:
            return {
                "grade": Grade(
                    grade="none",
                    evidence_ids=[],
                    missing_requirements=[],
                    reason="No candidates",
                )
            }
        aliases = {f"E{i + 1}": hit.chunk.chunk_id for i, hit in enumerate(hits)}
        result = await context.llm.ask(
            "rag_grade",
            {
                "query": query,
                "evidence": [
                    {"id": key, "text": hit.chunk.text}
                    for key, hit in zip(aliases, hits, strict=True)
                ],
            },
            Grade,
        )
        if any(key not in aliases for key in result.evidence_ids):
            raise RagFailure(
                "model_response_invalid",
                "Evidence grader invented an evidence reference",
            )
        normalized = re.sub(r"\s+", " ", query.casefold())
        grounded = [
            item
            for item in result.missing_requirements
            if item.strip() and re.sub(r"\s+", " ", item.casefold()) in normalized
        ]
        if len(grounded) != len(result.missing_requirements):
            context.diagnostics["discarded_unanchored_requirements"] = True
        result = result.model_copy(update={"missing_requirements": grounded})
        if (result.grade == "adequate" and not result.evidence_ids) or (
            result.grade == "none" and result.evidence_ids
        ):
            raise RagFailure(
                "model_response_invalid", "Evidence grade contradicts its citations"
            )
        return {
            "grade": result.model_copy(
                update={"evidence_ids": [aliases[key] for key in result.evidence_ids]}
            )
        }

    async def correct(state):
        focused = "\n".join(state["grade"].missing_requirements) or query
        context.diagnostics["corrective_query"] = focused
        return {"query": focused, "corrections": 1}

    def route(state):
        return (
            "correct"
            if state["grade"].grade != "adequate" and state["corrections"] == 0
            else END
        )

    graph = StateGraph(CorrectiveState)
    graph.add_node("search", search)
    graph.add_node("grade", grade)
    graph.add_node("correct", correct)
    graph.add_edge(START, "search")
    graph.add_edge("search", "grade")
    graph.add_conditional_edges("grade", route)
    graph.add_edge("correct", "search")
    result = await graph.compile().ainvoke(
        {"query": query, "corrections": 0}, config={"recursion_limit": 10}
    )
    final = result["grade"]
    context.diagnostics.update(
        grade=final.grade, grade_reason=final.reason, corrections=result["corrections"]
    )
    return [hit for hit in result["hits"] if hit.chunk.chunk_id in final.evidence_ids]
