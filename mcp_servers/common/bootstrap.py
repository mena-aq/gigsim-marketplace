"""Provision local persona users. MCP tokens must be supplied via environment."""

import asyncio
import os

from dotenv import dotenv_values
from sqlalchemy import delete, select

from apps.api.models import MCPCredential, User
from mcp_servers.common.runtime import Runtime
from mcp_servers.common.security import PERSONAS, token_hash


async def main():
    environment = {**dotenv_values(".env"), **os.environ}
    tokens = {
        persona: environment.get(f"MCP_TOKEN_{persona.upper()}", "")
        for persona in PERSONAS
    }
    if any(len(token) < 24 for token in tokens.values()) or len(
        set(tokens.values())
    ) != len(tokens):
        raise SystemExit(
            "Set three distinct MCP_TOKEN_<PERSONA> values, each at least 24 characters"
        )
    runtime = Runtime()
    try:
        async with runtime.sessions() as session, session.begin():
            for persona, token in tokens.items():
                email = f"{persona}@gigbid.test"
                user = (
                    await session.execute(select(User).where(User.email == email))
                ).scalar_one_or_none()
                if user is None:
                    user = User(email=email, persona=persona)
                    session.add(user)
                    await session.flush()
                await session.execute(
                    delete(MCPCredential).where(MCPCredential.user_id == user.id)
                )
                session.add(
                    MCPCredential(user_id=user.id, token_hash=token_hash(token))
                )
        print(
            "Provisioned three local persona users; tokens were not printed or stored in plaintext"
        )
    finally:
        await runtime.close()


if __name__ == "__main__":
    asyncio.run(main())
