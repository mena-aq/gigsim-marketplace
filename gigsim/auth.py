"""Bearer-token auth: one token per freelancer persona, plus a separate admin token."""

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_freelancer(
    request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)
) -> str:
    """Resolve the freelancer id from the bearer token, or raise 401."""
    if creds is None or not creds.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    tokens = request.app.state.settings.freelancer_tokens
    for freelancer_id, value in tokens.items():
        if creds.credentials == value:
            return freelancer_id
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid bearer token")


async def require_admin(request: Request) -> None:
    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else None
    if not token or token != request.app.state.settings.admin_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Admin token required")
