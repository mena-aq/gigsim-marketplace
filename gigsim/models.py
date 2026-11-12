"""SQLAlchemy models — the GigSim tables (GigSim owns its own database)."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from gigsim.util import utcnow

JSONType = JSON().with_variant(postgresql.JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    skills: Mapped[list] = mapped_column(JSONType, default=list)
    budget_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    budget_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    timeline_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    screening_questions: Mapped[list] = mapped_column(JSONType, default=list)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_scam: Mapped[bool] = mapped_column(Boolean, default=False)
    has_injection: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    total_spend: Mapped[float] = mapped_column(Float, default=0.0)
    hire_rate: Mapped[float] = mapped_column(Float, default=0.0)
    avg_rating: Mapped[float] = mapped_column(Float, default=0.0)
    payment_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_bad_actor: Mapped[bool] = mapped_column(Boolean, default=False)
    hidden_preferences: Mapped[dict] = mapped_column(JSONType, default=dict)
    reviews: Mapped[list] = mapped_column(JSONType, default=list)


class Proposal(Base):
    __tablename__ = "proposals"
    __table_args__ = (UniqueConstraint("freelancer_id", "idempotency_key", name="uq_proposal_idem"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(64), ForeignKey("jobs.id"), index=True)
    freelancer_id: Mapped[str] = mapped_column(String(64), index=True)
    cover_letter: Mapped[str] = mapped_column(Text)
    skills_mentioned: Mapped[list] = mapped_column(JSONType, default=list)
    screening_answers: Mapped[list] = mapped_column(JSONType, default=list)
    status: Mapped[str] = mapped_column(String(16), default="submitted", index=True)
    connects_spent: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(128), index=True)
    conversation_id: Mapped[str] = mapped_column(String(140), index=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(140), index=True)
    sender: Mapped[str] = mapped_column(String(16))
    body: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Connects(Base):
    __tablename__ = "connects"

    freelancer_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    balance: Mapped[int] = mapped_column(Integer, default=0)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    freelancer_id: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
