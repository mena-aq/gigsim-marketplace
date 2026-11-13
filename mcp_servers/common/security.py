"""Authenticated identity, payload binding, and audit redaction."""

import hashlib
import json
import logging
import re
from contextvars import ContextVar
from dataclasses import dataclass

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from sqlalchemy import select

from apps.api.models import MCPCredential, User
from mcp_servers.common.errors import ToolFailure

TRACE_ID: ContextVar[str | None] = ContextVar("mcp_trace_id", default=None)
PERSONAS = ("ml_engineer", "fullstack_dev", "data_analyst")


@dataclass(frozen=True)
class Identity:
    user_id: str
    persona: str


def identity() -> Identity:
    token = get_access_token()
    if token is None or not token.subject or token.claims is None:
        raise ToolFailure("unauthorized", "A valid MCP bearer token is required")
    persona = token.claims.get("persona")
    if persona not in PERSONAS:
        raise ToolFailure("unauthorized", "No assigned persona")
    return Identity(token.subject, persona)


def fingerprint(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class DatabaseTokenVerifier(TokenVerifier):
    def __init__(self, sessions, resource: str | None = None):
        self.sessions = sessions
        self.resource = resource

    async def verify_token(self, token: str) -> AccessToken | None:
        async with self.sessions() as session:
            user = (
                await session.execute(
                    select(User)
                    .join(MCPCredential, MCPCredential.user_id == User.id)
                    .where(MCPCredential.token_hash == token_hash(token))
                )
            ).scalar_one_or_none()
        if user is None or user.persona not in PERSONAS:
            return None
        return AccessToken(
            token=token,
            client_id=user.id,
            subject=user.id,
            scopes=["gigbid"],
            claims={"persona": user.persona},
            resource=self.resource,
        )


def mask(value):
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if any(
                word in key.lower()
                for word in (
                    "token",
                    "secret",
                    "password",
                    "authorization",
                    "payment",
                    "card_number",
                    "account_number",
                )
            )
            else mask(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [mask(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/-]+=*", "Bearer [REDACTED]", value)
        value = re.sub(r"\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]+", "[TOKEN]", value)
        value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[EMAIL]", value)
        return re.sub(r"(?<!\w)\+?\d[\d ()-]{7,}\d(?!\w)", "[PHONE_OR_PAYMENT]", value)
    return value


class RedactLogs(logging.Filter):
    """Mask messages at handlers, including third-party SDK validation logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = mask(record.getMessage())
        record.args = ()
        if record.exc_info:
            # SDK stack traces may embed raw input; retain only the exception type.
            record.msg += " [" + record.exc_info[0].__name__ + "]"
            record.exc_info = None
            record.exc_text = None
        return True


def install_log_redaction() -> None:
    loggers = [logging.getLogger()] + [
        logger
        for logger in logging.Logger.manager.loggerDict.values()
        if isinstance(logger, logging.Logger)
    ]
    for logger in loggers:
        for handler in logger.handlers:
            if not any(isinstance(item, RedactLogs) for item in handler.filters):
                handler.addFilter(RedactLogs())
