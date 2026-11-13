"""Initial tenant-owned application records. Marketplace data is copied via MCP later."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    persona: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class OwnedRecord:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class Job(OwnedRecord, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "marketplace", "external_id"),
        UniqueConstraint("user_id", "id"),
    )
    marketplace: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="new")


class Proposal(OwnedRecord, Base):
    __tablename__ = "proposals"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key"),
        UniqueConstraint("user_id", "id"),
        ForeignKeyConstraint(["user_id", "job_id"], ["jobs.user_id", "jobs.id"]),
    )
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    cover_letter: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="drafted")
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    connects_cost: Mapped[int] = mapped_column(Integer, default=0)


class Message(OwnedRecord, Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("user_id", "marketplace", "external_id"),)
    marketplace: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str | None] = mapped_column(String(128))
    conversation_id: Mapped[str] = mapped_column(String(160), index=True)
    sender: Mapped[str] = mapped_column(String(32))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="drafted")


class PipelineCard(OwnedRecord, Base):
    __tablename__ = "pipeline_cards"
    __table_args__ = (
        UniqueConstraint("user_id", "job_id"),
        ForeignKeyConstraint(["user_id", "job_id"], ["jobs.user_id", "jobs.id"]),
    )
    job_id: Mapped[str] = mapped_column(String(36))
    stage: Mapped[str] = mapped_column(String(32), default="drafted")


class AuditLog(OwnedRecord, Base):
    __tablename__ = "audit_log"
    action: Mapped[str] = mapped_column(String(100))
    trace_id: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[dict] = mapped_column(JSON().with_variant(JSONB(), "postgresql"))
