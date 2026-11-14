"""Remove sentences with unsupported experience claims; never invent replacements."""

import re
from itertools import pairwise
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, create_model

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


def plain_nonexperience(text: str, kind: str) -> bool:
    """Recognize a small set of harmless greetings and explicit future intentions."""
    value = text.strip()
    if kind == "nonfactual":
        if (
            value.endswith("?")
            and re.match(
                r"(?:what|which|when|how|could you|can you|do you|would you)\b",
                value,
                re.IGNORECASE,
            )
            and not re.search(r"\b(?:I|my|we|our)\b", value, re.IGNORECASE)
        ):
            return True
        return bool(
            re.fullmatch(
                r"(?:hi|hello|dear client|thank you|thanks|best regards|regards)[!,. ]*",
                value,
                re.IGNORECASE,
            )
        )
    if kind != "intent":
        return False
    # Past achievements in a future-looking sentence still require evidence.
    past = r"\b(?:built|delivered|achieved|reduced|deployed|worked|used|led|managed|created|developed|years?|experience|previously)\b"
    prefix = re.match(
        r"(?:I (?:will|would|can|propose|plan to|aim to|estimate|expect to|am ready to)|ready to|let['’]s|could we|shall we)\b",
        value,
        re.IGNORECASE,
    )
    return (
        bool(prefix)
        and not re.search(past, value, re.IGNORECASE)
        and not re.search(
            r"\b(?:I|my|we|our|have|had|was|were|am)\b",
            value[prefix.end() :],
            re.IGNORECASE,
        )
    )


def validate_claims(
    text: str, claims: list[AtomicClaim], evidence: list[Chunk]
) -> list[AtomicClaim]:
    """Validate every claim/citation and reject unchecked factual sentence text."""
    aliases = {f"E{i + 1}": chunk for i, chunk in enumerate(evidence)}
    covered = [False] * len(text)
    for claim in claims:
        if (
            not claim.text.strip()
            or claim.text not in text
            or any(key not in aliases for key in claim.evidence_ids)
        ):
            raise RagFailure(
                "model_response_invalid", "Verifier invented a claim or citation"
            )
        location = text.find(claim.text)
        covered[location : location + len(claim.text)] = [True] * len(claim.text)
        if claim.kind != "experience" and (
            claim.status != "supported"
            or claim.evidence_ids
            or not plain_nonexperience(claim.text, claim.kind)
        ):
            claim.status = "unsupported"
            claim.reason = (
                "Nonexperience classification is inconsistent or needs evidence review"
            )
        if (
            claim.kind == "experience"
            and claim.status != "unsupported"
            and not claim.evidence_ids
        ):
            raise RagFailure(
                "model_response_invalid", "A supported experience claim needs evidence"
            )
        if claim.kind == "experience" and claim.status == "supported":
            cited = " ".join(aliases[key].text for key in claim.evidence_ids)
            numbers = set(re.findall(r"\d+(?:[.,]\d+)*", claim.text))
            if not numbers <= set(re.findall(r"\d+(?:[.,]\d+)*", cited)):
                claim.status = "unsupported"
                claim.reason = "A numeric detail is absent from cited evidence"
        claim.evidence_ids = [aliases[key].chunk_id for key in claim.evidence_ids]
    residual = "".join(c if not covered[i] else " " for i, c in enumerate(text))
    if re.sub(r"\b(?:and|or|but)\b|[\W_]", "", residual, flags=re.IGNORECASE):
        raise RagFailure("model_response_invalid", "Verifier left text unchecked")
    return claims


def sentence_schema(index: int, evidence_count: int, exact_text: str | None = None):
    """Constrain decoder output to one source index and available citation IDs."""
    citation = (
        Literal[tuple(f"E{i + 1}" for i in range(evidence_count))]
        if evidence_count
        else str
    )
    constraints = {"text": (Literal[exact_text], ...)} if exact_text is not None else {}
    claim = create_model(
        "GroundedClaim",
        __base__=AtomicClaim,
        evidence_ids=(list[citation], Field(max_length=evidence_count)),
        **constraints,
    )
    sentence = create_model(
        "SourceSentence",
        __base__=IndexedSentence,
        index=(Literal[index], ...),
        claims=(
            list[claim],
            Field(min_length=1, max_length=1 if exact_text is not None else 10),
        ),
    )
    return create_model(
        "SentenceJudgment",
        sentences=(list[sentence], Field(min_length=1, max_length=1)),
    )


async def verify_claims(draft: str, evidence: list[Chunk], llm) -> VerificationReport:
    """Verify factual sentences individually; preserve validated plain intentions."""
    sentences = []
    failures = []
    coverage_retries = []
    before = len(llm.usage)
    excerpts = [
        {"id": f"E{i + 1}", "text": chunk.text} for i, chunk in enumerate(evidence)
    ]
    for index, (start, end) in enumerate(sentence_spans(draft)):
        text = draft[start:end]
        plain_kind = next(
            (
                kind
                for kind in ("intent", "nonfactual")
                if plain_nonexperience(text, kind)
            ),
            None,
        )
        if plain_kind:
            claims = [
                AtomicClaim(
                    text=text,
                    kind=plain_kind,
                    status="supported",
                    evidence_ids=[],
                    reason="Plain nonexperience expression",
                )
            ]
        else:
            try:
                response = await llm.ask(
                    "rag_verify",
                    {
                        "sentences": [{"index": index, "text": text}],
                        "evidence": excerpts,
                    },
                    sentence_schema(index, len(evidence)),
                )
                if len(response.sentences) != 1 or response.sentences[0].index != index:
                    raise RagFailure(
                        "model_response_invalid",
                        "Verifier omitted or repeated a sentence",
                    )
                try:
                    claims = validate_claims(
                        text, response.sentences[0].claims, evidence
                    )
                except RagFailure as exc:
                    if not evidence or exc.message != "Verifier left text unchecked":
                        raise
                    # Do not accept partially copied text. Retry with the entire
                    # original sentence fixed by the decoder and grade every fact.
                    coverage_retries.append(index)
                    response = await llm.ask(
                        "rag_verify_sentence",
                        {
                            "sentences": [{"index": index, "text": text}],
                            "evidence": excerpts,
                        },
                        sentence_schema(index, len(evidence), exact_text=text),
                    )
                    claims = validate_claims(
                        text, response.sentences[0].claims, evidence
                    )
            except (RagFailure, ValidationError) as exc:
                if isinstance(exc, ValidationError):
                    exc = RagFailure(
                        "model_response_invalid",
                        "Verifier response failed source/citation schema",
                    )
                failures.append(
                    {
                        "start": start,
                        "end": end,
                        "code": exc.code,
                        "message": exc.message,
                    }
                )
                sentences.append(
                    VerifiedSentence(
                        text=text,
                        start=start,
                        end=end,
                        claims=[],
                        kept=False,
                        verified=False,
                    )
                )
                continue
        sentences.append(
            VerifiedSentence(
                text=text,
                start=start,
                end=end,
                claims=claims,
                kept=all(c.status == "supported" for c in claims),
            )
        )
    return VerificationReport(
        cleaned_draft="\n".join(s.text for s in sentences if s.kept),
        sentences=sentences,
        status="verified" if all(s.verified for s in sentences) else "needs_attention",
        diagnostics={
            "llm_usage": llm.usage[before:],
            "failures": failures,
            "coverage_retries": coverage_retries,
        },
    )
