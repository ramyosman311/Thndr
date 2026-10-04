"""Centralized API authentication and identity.

Every non-health route is protected at router-mounting level (see
app/api/router.py), never per-route, so no route added later can ship
unauthenticated by omission:

  * `verify_internal_proxy_token` -- the optional server-to-server trust
    signal sent by our own Vercel proxy (`X-Internal-Proxy-Token`).
  * `get_current_user` -- the REAL gate: verifies the caller's Supabase JWT
    (`require_supabase_user`) and resolves the local user. Everything user-
    owned is scoped by that verified `user.id` (P0-3C), never by an id the
    client supplied.

`API_AUTH_TOKEN` (P0-2) is no longer an `Authorization` credential: the
`Authorization` header now carries the user's Supabase JWT. The internal
token is a separate header, is NOT identity, and can never substitute for
the JWT: absent -> allowed (native/Capacitor clients never send it),
present and correct -> allowed, present and incorrect -> 401 -- and a
valid JWT is still required either way.

`DEV_MODE` has no effect on either dependency: there is no development
bypass of JWT verification or of ownership scoping.
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
    never boot without API_AUTH_TOKEN set -- the web proxy's
    `X-Internal-Proxy-Token` could never be verified, so every proxied
    request would be rejected. Same fail-closed shape as
    app/seed/__main__.py's production guard -- refuse via sys.exit(1) rather
    than proceed with a warning."""
    settings = get_settings()
    if not settings.dev_mode and not settings.api_auth_token:
        print(
            "Refusing to start with DEV_MODE=false and no API_AUTH_TOKEN configured -- "
            "the web proxy's internal token could not be verified. "
            "Set API_AUTH_TOKEN (or DEV_MODE=true for local development only).",
            file=sys.stderr,
        )
        sys.exit(1)


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
    accepted), and never falls back to any DEV_MODE bypass. Any failure whatsoever --
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
    present and wrong -> 401. It reads its own header, never
    `Authorization` (which carries the user's JWT). Attached to every
    protected router alongside `get_current_user` -- see app/api/router.py.
    """
    if x_internal_proxy_token is None:
        return

    settings = get_settings()
    if not settings.api_auth_token or not hmac.compare_digest(x_internal_proxy_token, settings.api_auth_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
