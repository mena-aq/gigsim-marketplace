"""Internal retrieval and verification objects; no marketplace capabilities."""

from typing import Literal

from pydantic import BaseModel, Field

from mcp_servers.common.errors import ToolFailure


class RagFailure(ToolFailure):
    pass


class Document(BaseModel):
    id: str
    persona: str
    type: str
    source: str
    source_hash: str
    text: str
    date: str | None = None
    outcome: str | None = None
    project: str | None = None
    industry: str | None = None
    skills: list[str] = Field(default_factory=list)


class Chunk(Document):
    chunk_id: str
    start: int
    end: int


class Hit(BaseModel):
    chunk: Chunk
    score: float


class Retrieval(BaseModel):
    hits: list[Hit]
    variant: str
    status: Literal["complete", "partial", "empty"] = "complete"
    diagnostics: dict = Field(default_factory=dict)


class Requirements(BaseModel):
    items: list[str] = Field(min_length=1, max_length=6)


class RequirementSelection(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=6)


class Grade(BaseModel):
    grade: Literal["adequate", "weak", "none"]
    evidence_ids: list[str]
    missing_requirements: list[str]
    reason: str


class AtomicClaim(BaseModel):
    text: str
    kind: Literal["experience", "intent", "nonfactual"]
    status: Literal["supported", "partly_supported", "unsupported"]
    evidence_ids: list[str]
    reason: str


class SentenceJudgment(BaseModel):
    claims: list[AtomicClaim] = Field(min_length=1, max_length=10)


class VerifiedSentence(BaseModel):
    text: str
    start: int
    end: int
    claims: list[AtomicClaim]
    kept: bool
    verified: bool = True


class VerificationReport(BaseModel):
    cleaned_draft: str
    sentences: list[VerifiedSentence]
    status: Literal["verified", "needs_attention"]
    diagnostics: dict = Field(default_factory=dict)
