"""Pydantic request/response schemas for the GigSim API."""

from datetime import datetime

from pydantic import BaseModel, Field


class JobOut(BaseModel):
    id: str
    title: str
    description: str
    skills: list = []
    budget_min: float | None = None
    budget_max: float | None = None
    timeline_days: int | None = None
    screening_questions: list = []
    category: str | None = None
    client_id: str | None = None
    posted_at: datetime | None = None
    status: str

    model_config = {"from_attributes": True}


class JobPage(BaseModel):
    items: list[JobOut]
    total: int
    page: int
    page_size: int


class JobGroundTruth(BaseModel):
    """Admin-only view: exposes the labels GigBid's agents are supposed to detect."""

    id: str
    title: str
    is_scam: bool
    has_injection: bool
    status: str

    model_config = {"from_attributes": True}


class ClientOut(BaseModel):
    id: str
    name: str
    total_spend: float
    hire_rate: float
    avg_rating: float
    payment_verified: bool

    model_config = {"from_attributes": True}


class ClientHistoryProposal(BaseModel):
    job_id: str
    job_title: str
    freelancer_id: str
    status: str
    connects_spent: int
    submitted_at: datetime


class ClientHistory(BaseModel):
    client: ClientOut
    proposals_received: int
    past_proposals: list[ClientHistoryProposal]
    reviews: list[str]


class ProposalIn(BaseModel):
    job_id: str
    cover_letter: str = Field(min_length=1)
    skills_mentioned: list[str] = []
    screening_answers: list = []
    idempotency_key: str = Field(min_length=1, max_length=128)
    dry_run: bool = False


class ProposalOut(BaseModel):
    id: int
    job_id: str
    freelancer_id: str
    status: str
    skills_mentioned: list = []
    connects_spent: int
    conversation_id: str
    submitted_at: datetime
    idempotent_replay: bool = False
    connects_remaining: int | None = None


class MessageIn(BaseModel):
    conversation_id: str
    body: str = Field(min_length=1)
    dry_run: bool = False


class MessageOut(BaseModel):
    id: int
    conversation_id: str
    sender: str
    body: str
    sent_at: datetime

    model_config = {"from_attributes": True}


class ConversationSummary(BaseModel):
    conversation_id: str
    job_id: str
    proposal_status: str
    last_message: str | None = None
    last_message_at: datetime | None = None
    message_count: int


class ConnectsOut(BaseModel):
    freelancer_id: str
    balance: int


class StreamRelease(BaseModel):
    released: list[str]
    remaining: int


class AdminStats(BaseModel):
    jobs_total: int
    jobs_open: int
    jobs_pending: int
    jobs_filled: int
    scams: int
    injections: int
    clients: int
    bad_actors: int
    proposals: int
    messages: int
