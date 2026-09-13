"""Centralized API authentication (P0-2, single-user shared-token stage).

Everything funnels through the one dependency below, attached once at
router-mounting level (see app/api/router.py) -- never per-route. This
is deliberate: migrating to per-user auth later (see DEPLOYMENT.md,
"Authentication") only means changing what `require_api_token` verifies
(a Supabase-issued JWT instead of a static shared secret) and what the
frontend's proxy forwards -- the router wiring never has to change.

`DEV_MODE=true` bypasses this entirely -- the pre-existing, documented
contract in .env.example ("Development mode disables authentication
enforcement") and ARCHITECTURE.md, "Authentication Boundary". This module
finally implements that contract; it does not introduce a new one.

Not per-user identity, not a session, not a JWT -- a single shared secret
compared in constant time. That is the whole mechanism this phase needs
for a single-user deployment, and no more.
"""

import hmac
import sys

from fastapi import Header, HTTPException, status

from app.core.config import get_settings

_BEARER_PREFIX = "Bearer "


def ensure_auth_configured() -> None:
    """Fail closed at process startup (called from app.main's lifespan,
    before the app accepts any traffic): a DEV_MODE=false process must
    never boot without API_AUTH_TOKEN set, since that would silently
    reintroduce the fully-open API this phase exists to close. Same
    fail-closed shape as app/seed/__main__.py's production guard --
    refuse via sys.exit(1) rather than proceed with a warning."""
    settings = get_settings()
    if not settings.dev_mode and not settings.api_auth_token:
        print(
            "Refusing to start with DEV_MODE=false and no API_AUTH_TOKEN configured -- "
            "every non-health API route would otherwise be unauthenticated in production. "
            "Set API_AUTH_TOKEN (or DEV_MODE=true for local development only).",
            file=sys.stderr,
        )
        sys.exit(1)


async def require_api_token(authorization: str | None = Header(default=None)) -> None:
    """FastAPI dependency: expects `Authorization: Bearer <token>` and
    compares it to API_AUTH_TOKEN with hmac.compare_digest (constant-time,
    no early-exit timing leak). A no-op whenever DEV_MODE=true.

    Raising HTTPException(401) here (rather than returning a bool) is
    what makes this usable as a router-level `dependencies=[...]` entry
    -- FastAPI evaluates it before any route handler in that router runs,
    without needing every route to declare it individually."""
    settings = get_settings()
    if settings.dev_mode:
        return

    token = authorization[len(_BEARER_PREFIX):] if authorization and authorization.startswith(_BEARER_PREFIX) else ""

    if not token or not hmac.compare_digest(token, settings.api_auth_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
