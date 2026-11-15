"""Validated handoffs and review decisions."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from mcp_servers.common.schemas import ScreeningAnswer


class JobSpec(BaseModel):
    job_id: str
    title: str
    deliverables: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    budget_min: float | None = None
    budget_max: float | None = None
    timeline_days: int | None = None
    screening_questions: list[str] = Field(default_factory=list)
    hidden_needs: list[str] = Field(default_factory=list)


class RiskReport(BaseModel):
    score: float = Field(ge=0, le=1)
    flags: list[str] = Field(default_factory=list)
    explanation: str


class RiskFinding(BaseModel):
    level: Literal["caution", "high"]
    source: Literal["job", "history"]
    quote: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=500)


class RiskAssessment(BaseModel):
    findings: list[RiskFinding] = Field(max_length=5)


class FitReport(BaseModel):
    score: float = Field(ge=0, le=1)
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    requirement_matches: list["RequirementMatch"] = Field(default_factory=list)


class RequirementMatch(BaseModel):
    requirement: str
    evidence_ids: list[str] = Field(default_factory=list)
    reason: str


class BidDecision(BaseModel):
    action: Literal["bid", "watch", "skip"]
    reason: str


class PriceQuote(BaseModel):
    amount: float = Field(gt=0)
    rationale: str
    connects_balance: int = Field(ge=0)
    connects_cost: int = Field(default=0, ge=0)


class AgentStep(BaseModel):
    """One ReAct step of the single-agent baseline: call a tool, or stop looking."""

    action: Literal["get_client_history", "search_evidence", "finish"]
    query: str = Field(default="", max_length=300)


class SingleAgentResult(BaseModel):
    action: Literal["bid", "watch", "skip"]
    reason: str = Field(max_length=500)
    cover_letter: str = Field(default="", max_length=2500)
    price: float = Field(default=0, ge=0)


class ProposalDraft(BaseModel):
    job_id: str
    cover_letter: str
    screening_answers: list[ScreeningAnswer] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    status: str = "pending_review"


class Critique(BaseModel):
    verdict: Literal["pass", "revise"]
    issues: list[str] = Field(default_factory=list)


class ComplianceVerdict(BaseModel):
    passed: bool
    violations: list[str] = Field(default_factory=list)


class ComplianceFinding(BaseModel):
    category: Literal[
        "off_platform_contact",
        "personal_contact_details",
        "guaranteed_outcome",
        "unsupported_experience",
    ]
    quote: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=500)


class ComplianceAssessment(BaseModel):
    findings: list[ComplianceFinding] = Field(max_length=5)


class ConversationIntent(BaseModel):
    intent: Literal["question", "negotiation", "interview_request", "scam_signal"]
    reason: str


class ApprovalRequest(BaseModel):
    action: Literal["approve", "edit", "reject"]
    review_hash: str = Field(min_length=64, max_length=64)
    cover_letter: str | None = Field(default=None, min_length=1, max_length=20000)
    screening_answers: list[ScreeningAnswer] | None = None
    reason: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def valid_action(self):
        if self.action == "reject" and not self.reason.strip():
            raise ValueError("A rejection reason is required")
        if (
            self.action == "edit"
            and self.cover_letter is None
            and self.screening_answers is None
        ):
            raise ValueError("An edit must contain changed text")
        if self.action != "edit" and (
            self.cover_letter is not None or self.screening_answers is not None
        ):
            raise ValueError("Only edit actions may change text")
        return self
