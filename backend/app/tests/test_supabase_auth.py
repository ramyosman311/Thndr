"""P0-3B: Supabase Auth JWT verification and identity resolution.

Covers `require_supabase_user` (signature/issuer/audience/expiration
verification via a faked JWKS client -- never a real network call to a
live Supabase project, matching this repo's sandboxed-network testing
convention), `get_current_user` (get-or-create local shadow identity,
stable across repeated calls for the same UUID), and
`verify_internal_proxy_token` (the separate, optional-if-present
server-to-server trust signal introduced alongside it).

Uses a locally generated RSA keypair to sign test tokens exactly the way
Supabase itself signs access tokens (RS256, asymmetric) -- never HS256,
never an unsigned token -- so these tests exercise the real cryptographic
verification path, not just claim inspection.
"""

import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from app.core import auth as auth_module
from app.core.config import Settings
from app.models.user import User

SUPABASE_URL = "https://test-project.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
AUDIENCE = "authenticated"

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_KEY = _PRIVATE_KEY.public_key()

# A second, unrelated keypair: signing with this and presenting it against
# the "real" JWKS public key above is what a forged/tampered token looks like.
_ATTACKER_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _FakeSigningKey:
    def __init__(self, key):
        self.key = key


class _FakeJWKClient:
    """Stands in for jwt.PyJWKClient: returns a fixed public key regardless
    of the token's `kid`, so tests control the "real" JWKS key directly
    instead of needing a live network fetch."""

    def __init__(self, key):
        self._key = key

    def get_signing_key_from_jwt(self, token: str) -> _FakeSigningKey:
        return _FakeSigningKey(self._key)


def _settings(**overrides) -> Settings:
    defaults = {"SUPABASE_URL": SUPABASE_URL, "SUPABASE_JWT_AUDIENCE": AUDIENCE}
    defaults.update(overrides)
    return Settings(**defaults)


def _use_settings(monkeypatch, **overrides) -> None:
    monkeypatch.setattr(auth_module, "get_settings", lambda: _settings(**overrides))


def _use_fake_jwks(monkeypatch, *, key=None) -> None:
    client = _FakeJWKClient(key if key is not None else _PUBLIC_KEY)
    monkeypatch.setattr(auth_module, "_jwks_client", lambda jwks_url: client)


def _make_token(
    *,
    sub: str | None = None,
    iss: str = ISSUER,
    aud: str = AUDIENCE,
    exp: datetime | None = None,
    private_key=_PRIVATE_KEY,
    algorithm: str = "RS256",
) -> str:
    payload = {
        "sub": sub if sub is not None else str(uuid.uuid4()),
        "iss": iss,
        "aud": aud,
        "exp": exp if exp is not None else datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return jwt.encode(payload, private_key, algorithm=algorithm)


# --- require_supabase_user: header shape -----------------------------------


@pytest.mark.asyncio
async def test_rejects_missing_authorization_header(monkeypatch):
    _use_settings(monkeypatch)
    _use_fake_jwks(monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        await auth_module.require_supabase_user(authorization=None)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_rejects_malformed_authorization_header(monkeypatch):
    """Missing the `Bearer ` prefix entirely."""
    _use_settings(monkeypatch)
    _use_fake_jwks(monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        await auth_module.require_supabase_user(authorization="just-a-token-no-bearer-prefix")

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_rejects_malformed_jwt(monkeypatch):
    _use_settings(monkeypatch)
    _use_fake_jwks(monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        await auth_module.require_supabase_user(authorization="Bearer not-a-real-jwt")

    assert exc_info.value.status_code == 401


# --- require_supabase_user: cryptographic / claim verification -------------


@pytest.mark.asyncio
async def test_accepts_valid_token_and_resolves_supabase_user_uuid(monkeypatch):
    _use_settings(monkeypatch)
    _use_fake_jwks(monkeypatch)
    expected_uuid = uuid.uuid4()
    token = _make_token(sub=str(expected_uuid))

    resolved = await auth_module.require_supabase_user(authorization=f"Bearer {token}")

    assert resolved == expected_uuid


@pytest.mark.asyncio
async def test_rejects_expired_token(monkeypatch):
    _use_settings(monkeypatch)
    _use_fake_jwks(monkeypatch)
    token = _make_token(exp=datetime.now(timezone.utc) - timedelta(minutes=5))

    with pytest.raises(HTTPException) as exc_info:
        await auth_module.require_supabase_user(authorization=f"Bearer {token}")

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_rejects_invalid_signature(monkeypatch):
    """Token signed with a different (attacker) private key than the one
    the "real" JWKS endpoint serves -- signature verification must fail."""
    _use_settings(monkeypatch)
    _use_fake_jwks(monkeypatch)  # fake JWKS always returns the REAL public key
    forged_token = _make_token(private_key=_ATTACKER_PRIVATE_KEY)

    with pytest.raises(HTTPException) as exc_info:
        await auth_module.require_supabase_user(authorization=f"Bearer {forged_token}")

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_rejects_wrong_issuer(monkeypatch):
    _use_settings(monkeypatch)
    _use_fake_jwks(monkeypatch)
    token = _make_token(iss="https://some-other-project.supabase.co/auth/v1")

    with pytest.raises(HTTPException) as exc_info:
        await auth_module.require_supabase_user(authorization=f"Bearer {token}")

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_rejects_wrong_audience(monkeypatch):
    _use_settings(monkeypatch)
    _use_fake_jwks(monkeypatch)
    token = _make_token(aud="some-other-audience")

    with pytest.raises(HTTPException) as exc_info:
        await auth_module.require_supabase_user(authorization=f"Bearer {token}")

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_rejects_valid_token_when_supabase_url_unconfigured(monkeypatch):
    """Fails closed rather than treating an unconfigured project as
    "anything verifies"."""
    _use_settings(monkeypatch, SUPABASE_URL="")
    _use_fake_jwks(monkeypatch)
    token = _make_token()

    with pytest.raises(HTTPException) as exc_info:
        await auth_module.require_supabase_user(authorization=f"Bearer {token}")

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_does_not_bypass_verification_in_dev_mode(monkeypatch):
    """P0-2's DEV_MODE bypass is a separate mechanism for a separate
    dependency (`require_api_token`) and must never leak into this one:
    an invalid token is rejected even with DEV_MODE=true."""
    _use_settings(monkeypatch, DEV_MODE=True, SUPABASE_URL="")
    _use_fake_jwks(monkeypatch)
    token = _make_token()

    with pytest.raises(HTTPException) as exc_info:
        await auth_module.require_supabase_user(authorization=f"Bearer {token}")

    assert exc_info.value.status_code == 401


# --- verify_internal_proxy_token --------------------------------------------


@pytest.mark.asyncio
async def test_internal_token_absent_is_allowed(monkeypatch):
    """Native/Capacitor clients never send this header at all."""
    _use_settings(monkeypatch, API_AUTH_TOKEN="shared-proxy-secret")

    await auth_module.verify_internal_proxy_token(x_internal_proxy_token=None)  # must not raise


@pytest.mark.asyncio
async def test_internal_token_correct_is_allowed(monkeypatch):
    _use_settings(monkeypatch, API_AUTH_TOKEN="shared-proxy-secret")

    await auth_module.verify_internal_proxy_token(
        x_internal_proxy_token="shared-proxy-secret"
    )  # must not raise


@pytest.mark.asyncio
async def test_internal_token_incorrect_is_rejected(monkeypatch):
    _use_settings(monkeypatch, API_AUTH_TOKEN="shared-proxy-secret")

    with pytest.raises(HTTPException) as exc_info:
        await auth_module.verify_internal_proxy_token(x_internal_proxy_token="wrong-secret")

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_internal_token_present_but_none_configured_is_rejected(monkeypatch):
    """A present-but-unmatchable header must not silently pass just
    because the server has nothing configured to compare it to."""
    _use_settings(monkeypatch, API_AUTH_TOKEN="")

    with pytest.raises(HTTPException) as exc_info:
        await auth_module.verify_internal_proxy_token(x_internal_proxy_token="anything")

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_internal_token_never_substitutes_for_supabase_jwt(monkeypatch):
    """The internal proxy token dependency has no notion of user identity
    at all -- calling it successfully returns None, never a user/UUID,
    and it does not itself call require_supabase_user."""
    _use_settings(monkeypatch, API_AUTH_TOKEN="shared-proxy-secret")

    result = await auth_module.verify_internal_proxy_token(x_internal_proxy_token="shared-proxy-secret")

    assert result is None


# --- get_current_user: identity resolution ----------------------------------


@pytest.mark.asyncio
async def test_get_current_user_creates_local_user_for_new_supabase_uuid(db_session):
    supabase_uuid = uuid.uuid4()

    user = await auth_module.get_current_user(supabase_user_id=supabase_uuid, db=db_session)

    assert isinstance(user, User)
    assert user.id == supabase_uuid


@pytest.mark.asyncio
async def test_get_current_user_is_stable_across_repeated_calls(db_session):
    """Same Supabase UUID must always resolve to the same local user row
    (get-or-create, not create-a-new-row-every-time)."""
    supabase_uuid = uuid.uuid4()

    first = await auth_module.get_current_user(supabase_user_id=supabase_uuid, db=db_session)
    second = await auth_module.get_current_user(supabase_user_id=supabase_uuid, db=db_session)

    assert first.id == second.id == supabase_uuid


@pytest.mark.asyncio
async def test_get_current_user_distinguishes_different_supabase_uuids(db_session):
    first_uuid, second_uuid = uuid.uuid4(), uuid.uuid4()

    first_user = await auth_module.get_current_user(supabase_user_id=first_uuid, db=db_session)
    second_user = await auth_module.get_current_user(supabase_user_id=second_uuid, db=db_session)

    assert first_user.id != second_user.id
