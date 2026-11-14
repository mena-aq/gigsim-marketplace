"""Draft grounded text using evidence, feedback and promoted style preferences."""

from agent.execution import NodeContext
from agent.handoffs import ProposalDraft
from agent.state import GigBidState


async def writer(state: GigBidState, ctx: NodeContext) -> dict:
    from typing import Literal

    from pydantic import BaseModel, Field, create_model

    from mcp_servers.common.schemas import ScreeningAnswer

    questions = state["job"].get("screening_questions", [])
    settings = ctx.config["orchestration"]
    answer_schema = create_model(
        "PostedQuestionAnswer",
        __base__=ScreeningAnswer,
        question=(Literal[tuple(questions)] if questions else str, ...),
        answer=(
            str,
            Field(min_length=1, max_length=settings["screening_answer_characters"]),
        ),
    )
    schema = create_model(
        "GroundedDraftText",
        __base__=BaseModel,
        cover_letter=(
            str,
            Field(min_length=1, max_length=settings["writer_characters"]),
        ),
        screening_answers=(
            list[answer_schema],
            Field(min_length=len(questions), max_length=len(questions)),
        ),
    )
    draft = await ctx.ask(
        "writer",
        {
            "untrusted_job": state["job"],
            "evidence": [
                {"id": f"E{index + 1}", "text": item["text"]}
                for index, item in enumerate(state.get("evidence", []))
            ],
            "price": state.get("price"),
            "style_memory": state.get("style", []),
            "critique": state.get("critique"),
            "maximum_cover_letter_words": settings["writer_words"],
            "maximum_screening_answer_words": settings["screening_answer_words"],
            "screening_questions": questions,
        },
        schema,
    )
    indexed_answers = {
        answer["question"]: answer for answer in draft["screening_answers"]
    }
    if set(indexed_answers) != set(questions):
        from mcp_servers.common.errors import ToolFailure

        raise ToolFailure(
            "screening_mismatch", "Writer omitted or duplicated a screening answer"
        )
    draft["screening_answers"] = [indexed_answers[question] for question in questions]
    draft["job_id"] = state["job"]["id"]
    # Citations are established by the verifier, never trusted from the writer.
    draft["evidence_ids"] = [item["chunk_id"] for item in state.get("evidence", [])]
    return {
        "draft": ProposalDraft.model_validate(draft).model_dump(),
        "verification_failed": False,
        "revisions": state.get("revisions", -1) + 1,
    }
