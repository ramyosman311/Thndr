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

P0-3B adds `require_supabase_user` / `get_current_user` below: real,
per-user Supabase Auth JWT verification. Deliberately NOT wired into
app/api/router.py or any route in this phase -- see DECISIONS.md,
"P0-3A/B — Identity, Ownership, JWT Verification" for why every existing
endpoint's auth is left exactly as `require_api_token` above already has
it, pending a later phase's coordinated rollout with the frontend proxy.

`verify_internal_proxy_token` is a SEPARATE function reading a SEPARATE
header (`X-Internal-Proxy-Token`, not `Authorization`) from
`require_api_token`. It is a server-to-server trust signal only, never
identity, and must never substitute for `require_supabase_user`: absent
-> allowed (native clients never send it), present and correct ->
allowed, present and incorrect -> 401.
"""

import hmac
import sys
import uuid
from functools import lru_cache

import jwt
from fastapi import Depends, Header, HTTPException, status
from jwt import PyJWKClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db_session
from app.models.user import User

_BEARER_PREFIX = "Bearer "
_INTERNAL_PROXY_TOKEN_HEADER = "X-Internal-Proxy-Token"

# Supabase Auth signs with asymmetric keys only (RS256 today, ES256 is the
# documented alternative) -- never HS256/a shared secret, which is exactly
# what JWKS-based verification below defends against (see `require_supabase_user`).
_SUPABASE_JWT_ALGORITHMS = ["RS256", "ES256"]


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


@lru_cache(maxsize=None)
def _jwks_client(jwks_url: str) -> PyJWKClient:
    """Cached per JWKS URL for the process lifetime -- PyJWKClient itself
    caches fetched keys (cache_keys=True) and refreshes them only as
    needed, so this just avoids rebuilding the client object on every
    request. Tests replace this whole function via monkeypatch rather
    than exercising a real network fetch to a live Supabase project."""
    return PyJWKClient(jwks_url, cache_keys=True)


async def require_supabase_user(authorization: str | None = Header(default=None)) -> uuid.UUID:
    """FastAPI dependency: verifies `Authorization: Bearer <Supabase JWT>`
    end-to-end -- signature (via Supabase's own JWKS, asymmetric keys
    only), issuer, audience, and expiration -- and returns the verified
    `sub` claim as the Supabase Auth user's UUID.

    Never decodes the payload without verifying the signature first (no
    `options={"verify_signature": False}` anywhere here), never accepts
    an unsigned or HS256-shared-secret-signed token (only RS256/ES256 are
    accepted), and never falls back to any DEV_MODE bypass -- P0-2's
    `require_api_token` bypass is a separate mechanism for a separate
    header check and does not apply here. Any failure whatsoever --
    missing/malformed header, malformed JWT, expired, wrong
    issuer/audience, bad signature, missing `sub`, unconfigured
    SUPABASE_URL -- raises 401 with no further detail leaked to the caller.
    """
    if not authorization or not authorization.startswith(_BEARER_PREFIX):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    token = authorization[len(_BEARER_PREFIX):]

    settings = get_settings()
    if not settings.supabase_url:
        # Fail closed, not open: an unconfigured Supabase project must
        # never be treated as "any token verifies".
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        signing_key = _jwks_client(settings.supabase_jwks_url).get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=_SUPABASE_JWT_ALGORITHMS,
            issuer=settings.supabase_jwt_issuer,
            audience=settings.supabase_jwt_audience,
            options={"require": ["exp", "sub", "iss", "aud"]},
        )
        return uuid.UUID(str(payload["sub"]))
    except (jwt.PyJWTError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated") from exc


async def get_current_user(
    supabase_user_id: uuid.UUID = Depends(require_supabase_user),
    db: AsyncSession = Depends(get_db_session),
) -> User:
    """Get-or-create resolution of the local shadow `users` row (see
    app/models/user.py) for the verified Supabase Auth UUID. The same
    UUID always resolves to the same local row (stable identity); commits
    immediately on first sight of a UUID so the row is durable regardless
    of whatever the route handler itself does or doesn't commit. A race
    against a concurrent first request for the same UUID is resolved by
    rolling back and re-fetching after the primary key rejects the second
    insert.
    """
    user = await db.get(User, supabase_user_id)
    if user is not None:
        return user

    user = User(id=supabase_user_id)
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        user = await db.get(User, supabase_user_id)
        if user is None:
            raise
    else:
        await db.refresh(user)
    return user


async def verify_internal_proxy_token(
    x_internal_proxy_token: str | None = Header(default=None, alias=_INTERNAL_PROXY_TOKEN_HEADER),
) -> None:
    """Server-to-server trust signal ONLY -- never identity, never a
    substitute for `require_supabase_user`. Optional-if-present: absent
    (native/Capacitor clients, which never send it) -> allowed; present
    and equal to API_AUTH_TOKEN (the Vercel proxy, for Web) -> allowed;
    present and wrong -> 401. Deliberately independent of
    `require_api_token` (which reads `Authorization`, not this header)
    so that wiring this in later cannot collide with or weaken that
    existing, already-live check. Not attached to any route in this
    phase -- see module docstring.
    """
    if x_internal_proxy_token is None:
        return

    settings = get_settings()
    if not settings.api_auth_token or not hmac.compare_digest(x_internal_proxy_token, settings.api_auth_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
