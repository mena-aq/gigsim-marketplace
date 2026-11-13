"""Remove sentences with unsupported experience claims; never invent replacements."""

import re
from itertools import pairwise

from pydantic import BaseModel, Field

from rag.types import (
    AtomicClaim,
    Chunk,
    RagFailure,
    VerificationReport,
    VerifiedSentence,
)


class IndexedSentence(BaseModel):
    index: int
    claims: list[AtomicClaim] = Field(min_length=1, max_length=10)


class DraftJudgment(BaseModel):
    sentences: list[IndexedSentence]


def sentence_spans(text: str) -> list[tuple[int, int]]:
    boundaries = [0]
    for match in re.finditer(r"(?<=[.!?])\s+(?=[A-Z])|\n+", text):
        prefix = text[: match.start()]
        if any(
            prefix.endswith(abbreviation)
            for abbreviation in ("Dr.", "Mr.", "Ms.", "e.g.", "i.e.", "U.S.", "etc.")
        ):
            continue
        boundaries.append(match.end())
    boundaries.append(len(text))
    spans = []
    for start, end in pairwise(boundaries):
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start < end:
            spans.append((start, end))
    return spans


async def verify_claims(draft: str, evidence: list[Chunk], llm) -> VerificationReport:
    spans = sentence_spans(draft)
    aliases = {f"E{i + 1}": chunk.chunk_id for i, chunk in enumerate(evidence)}
    sentences = []
    failures = []
    before = len(llm.usage)
    for offset in range(0, len(spans), 4):
        batch = spans[offset : offset + 4]
        try:
            response = await llm.ask(
                "rag_verify",
                {
                    "sentences": [
                        {"index": offset + i, "text": draft[start:end]}
                        for i, (start, end) in enumerate(batch)
                    ],
                    "evidence": [
                        {"id": key, "text": chunk.text}
                        for key, chunk in zip(aliases, evidence, strict=True)
                    ],
                },
                DraftJudgment,
            )
            if sorted(item.index for item in response.sentences) != list(
                range(offset, offset + len(batch))
            ):
                raise RagFailure(
                    "model_response_invalid", "Verifier omitted or repeated a sentence"
                )
            for item in sorted(response.sentences, key=lambda item: item.index):
                start, end = spans[item.index]
                for claim in item.claims:
                    if (
                        not claim.text.strip()
                        or claim.text.casefold() not in draft[start:end].casefold()
                        or any(key not in aliases for key in claim.evidence_ids)
                    ):
                        raise RagFailure(
                            "model_response_invalid",
                            "Verifier invented a claim or citation",
                        )
                    if (
                        claim.kind == "experience"
                        and claim.status != "unsupported"
                        and not claim.evidence_ids
                    ):
                        raise RagFailure(
                            "model_response_invalid",
                            "A supported experience claim needs evidence",
                        )
                    if claim.kind == "experience" and claim.status == "supported":
                        cited = " ".join(
                            chunk.text
                            for key, chunk in zip(aliases, evidence, strict=True)
                            if key in claim.evidence_ids
                        )
                        claim_numbers = set(re.findall(r"\d+(?:[.,]\d+)*", claim.text))
                        evidence_numbers = set(re.findall(r"\d+(?:[.,]\d+)*", cited))
                        if not claim_numbers <= evidence_numbers:
                            claim.status = "unsupported"
                            claim.reason = "A numeric detail is absent from the cited evidence; equivalent number formats require review"
                    claim.evidence_ids = [aliases[key] for key in claim.evidence_ids]
                keep = all(
                    claim.kind != "experience" or claim.status == "supported"
                    for claim in item.claims
                )
                sentences.append(
                    VerifiedSentence(
                        text=draft[start:end],
                        start=start,
                        end=end,
                        claims=item.claims,
                        kept=keep,
                    )
                )
        except RagFailure as exc:
            failures.append(
                {
                    "start": batch[0][0],
                    "end": batch[-1][1],
                    "code": exc.code,
                    "message": exc.message,
                }
            )
            # Discard the whole failed batch rather than keeping a partial judgment.
            sentences = [
                sentence for sentence in sentences if sentence.start < batch[0][0]
            ]
            sentences.extend(
                VerifiedSentence(
                    text=draft[start:end],
                    start=start,
                    end=end,
                    claims=[],
                    kept=False,
                    verified=False,
                )
                for start, end in batch
            )
    return VerificationReport(
        cleaned_draft="\n".join(
            sentence.text for sentence in sentences if sentence.kept
        ),
        sentences=sentences,
        status="verified"
        if all(sentence.verified for sentence in sentences)
        else "needs_attention",
        diagnostics={"llm_usage": llm.usage[before:], "failures": failures},
    )
