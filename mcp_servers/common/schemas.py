"""Typed contracts shared across MCP boundaries."""

from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

T = TypeVar("T")


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, hide_input_in_errors=True
    )


class Failure(BaseModel):
    code: str
    message: str
    retryable: bool = False
    retry_after: float | None = None


class Result(BaseModel, Generic[T]):
    ok: bool
    data: T | None = None
    error: Failure | None = None
    trace_id: str


class SearchJobs(StrictModel):
    q: str = Field(default="", max_length=500)
    category: str | None = Field(default=None, max_length=120)
    budget_min: float | None = Field(default=None, ge=0)
    budget_max: float | None = Field(default=None, ge=0)
    page: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def valid_budget(self):
        if (
            self.budget_min is not None
            and self.budget_max is not None
            and self.budget_min > self.budget_max
        ):
            raise ValueError("budget_min must not exceed budget_max")
        return self


class JobOut(BaseModel):
    id: str
    title: str
    description: str
    skills: list[str]
    budget_min: float | None = None
    budget_max: float | None = None
    timeline_days: int | None = None
    screening_questions: list[str] = Field(default_factory=list)
    category: str | None = None
    client_id: str | None = None
    posted_at: datetime | None = None
    status: str


class JobPage(BaseModel):
    items: list[JobOut]
    total: int
    page: int
    page_size: int


class ClientOut(BaseModel):
    id: str
    name: str
    total_spend: float
    hire_rate: float
    avg_rating: float
    payment_verified: bool


class PastProposal(BaseModel):
    job_id: str
    job_title: str
    freelancer_id: str
    status: str
    connects_spent: int
    submitted_at: datetime


class ClientHistory(BaseModel):
    client: ClientOut
    proposals_received: int
    past_proposals: list[PastProposal]
    reviews: list[str]


class ConnectsOut(BaseModel):
    freelancer_id: str
    balance: int


class MessageOut(BaseModel):
    id: int
    conversation_id: str
    sender: str
    body: str
    sent_at: datetime


class WriteRequest(StrictModel):
    idempotency_key: str = Field(min_length=1, max_length=128)
    dry_run: bool = False


class ScreeningAnswer(StrictModel):
    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1, max_length=10000)


class ProposalRequest(WriteRequest):
    expected_connects_cost: int | None = Field(default=None, ge=0, le=1000)
    job_id: str = Field(min_length=1, max_length=64)
    cover_letter: str = Field(min_length=1, max_length=20000)
    skills_mentioned: list[str] = Field(default_factory=list, max_length=100)
    screening_answers: list[ScreeningAnswer] = Field(
        default_factory=list, max_length=50
    )


class MessageRequest(WriteRequest):
    conversation_id: str = Field(min_length=1, max_length=140)
    body: str = Field(min_length=1, max_length=20000)


class WriteResult(BaseModel):
    status: str
    payload: dict
    connects_cost: int = 0
    external_id: str | None = None
    draft_id: str | None = None


class EvidenceFilters(StrictModel):
    type: (
        Literal["cv", "case_study", "proposal", "review", "readme", "code", "document"]
        | None
    ) = None
    outcome: Literal["won", "replied", "ignored"] | None = None


class EvidenceQuery(StrictModel):
    requirement: str = Field(min_length=1, max_length=20000)
    k: int = Field(default=5, ge=1, le=20)
    filters: EvidenceFilters = Field(default_factory=EvidenceFilters)


class Evidence(BaseModel):
    id: str
    persona: str
    type: str
    source: str
    text: str
    date: str | None = None
    outcome: str | None = None
    project: str | None = None
    skills: list[str] = Field(default_factory=list)
    industry: str | None = None
    chunk_id: str | None = None
    score: float | None = None
    start: int | None = None
    end: int | None = None


class EvidencePage(BaseModel):
    items: list[Evidence]
    backend: Literal["v0", "v1", "v2", "v3", "v8"]
    retrieval_status: Literal["complete", "partial", "empty"] = "complete"
    diagnostics: dict = Field(default_factory=dict)


class VerificationRequest(StrictModel):
    draft: str = Field(min_length=1, max_length=20000)
    chunk_ids: list[str] = Field(default_factory=list, max_length=20)


class SkillList(BaseModel):
    skills: list[str]


class Slot(StrictModel):
    starts_at: AwareDatetime
    ends_at: AwareDatetime

    @model_validator(mode="after")
    def valid_interval(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class HoldRequest(WriteRequest):
    slot: Slot
    title: str = Field(min_length=1, max_length=200)


class EmailRequest(WriteRequest):
    to: str = Field(min_length=3, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)


class FreeSlots(BaseModel):
    timezone: Literal["Asia/Karachi"] = "Asia/Karachi"
    slots: list[Slot]
