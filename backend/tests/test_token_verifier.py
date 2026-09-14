from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.exceptions import PyJWKClientConnectionError

from app.auth.verifier import (
    AuthenticationError,
    AuthenticationServiceUnavailableError,
    SupabaseTokenVerifier,
)

ISSUER = "https://project.example.test/auth/v1"
USER_ID = "10000000-0000-0000-0000-000000000001"


class StaticSigningKey:
    def __init__(self, key) -> None:
        self.key = key


class StaticSigningKeyClient:
    def __init__(self, key) -> None:
        self._key = StaticSigningKey(key)

    def get_signing_key_from_jwt(self, token: str) -> StaticSigningKey:
        del token
        return self._key


class UnavailableSigningKeyClient:
    def get_signing_key_from_jwt(self, token: str) -> StaticSigningKey:
        del token
        raise PyJWKClientConnectionError("test provider outage")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def signing_key_pair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key, private_key.public_key()


def make_token(private_key, **claim_overrides) -> str:
    claims = {
        "iss": ISSUER,
        "aud": "authenticated",
        "exp": datetime.now(UTC) + timedelta(minutes=5),
        "sub": USER_ID,
        "email": "verified-user@example.test",
        **claim_overrides,
    }
    claims = {key: value for key, value in claims.items() if value is not None}
    return jwt.encode(claims, private_key, algorithm="ES256", headers={"kid": "test-key"})


def make_verifier(public_key) -> SupabaseTokenVerifier:
    return SupabaseTokenVerifier(
        supabase_url="https://project.example.test",
        publishable_key="non-secret-test-value",
        signing_key_client=StaticSigningKeyClient(public_key),
    )


@pytest.mark.anyio
async def test_verifier_accepts_a_valid_asymmetric_token(signing_key_pair) -> None:
    private_key, public_key = signing_key_pair

    identity = await make_verifier(public_key).verify(make_token(private_key))

    assert str(identity.user_id) == USER_ID
    assert identity.email == "verified-user@example.test"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "claim_overrides",
    [
        {"iss": "https://wrong-issuer.example.test/auth/v1"},
        {"aud": "wrong-audience"},
        {"exp": datetime.now(UTC) - timedelta(minutes=1)},
        {"sub": None},
    ],
)
async def test_verifier_rejects_invalid_required_claims(
    signing_key_pair,
    claim_overrides,
) -> None:
    private_key, public_key = signing_key_pair

    with pytest.raises(AuthenticationError):
        await make_verifier(public_key).verify(make_token(private_key, **claim_overrides))


@pytest.mark.anyio
async def test_verifier_rejects_an_invalid_signature(signing_key_pair) -> None:
    _, public_key = signing_key_pair
    unrelated_private_key = ec.generate_private_key(ec.SECP256R1())

    with pytest.raises(AuthenticationError):
        await make_verifier(public_key).verify(make_token(unrelated_private_key))


@pytest.mark.anyio
async def test_verifier_rejects_an_unsupported_algorithm(signing_key_pair) -> None:
    _, public_key = signing_key_pair
    token = jwt.encode(
        {
            "iss": ISSUER,
            "aud": "authenticated",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "sub": USER_ID,
        },
        "test-only-signing-value-that-is-long-enough-for-sha384-tests",
        algorithm="HS384",
    )

    with pytest.raises(AuthenticationError):
        await make_verifier(public_key).verify(token)


@pytest.mark.anyio
async def test_verifier_reports_an_unavailable_jwks_provider(signing_key_pair) -> None:
    private_key, _ = signing_key_pair
    verifier = SupabaseTokenVerifier(
        supabase_url="https://project.example.test",
        publishable_key="non-secret-test-value",
        signing_key_client=UnavailableSigningKeyClient(),
    )

    with pytest.raises(AuthenticationServiceUnavailableError):
        await verifier.verify(make_token(private_key))
