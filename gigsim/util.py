"""Small shared helpers."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Naive UTC timestamp (naive for consistency with seeded posted_at values)."""
    return datetime.now(UTC).replace(tzinfo=None)
