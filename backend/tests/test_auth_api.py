from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.dependencies import get_token_verifier
from app.auth.models import AuthenticatedUser
from app.auth.verifier import AuthenticationError, AuthenticationServiceUnavailableError
from app.main import app


class AcceptingVerifier:
    async def verify(self, token: str) -> AuthenticatedUser:
        assert token == "test-access-token"
        return AuthenticatedUser(
            user_id=UUID("10000000-0000-0000-0000-000000000001"),
            email="verified-user@example.test",
        )


class RejectingVerifier:
    async def verify(self, token: str) -> AuthenticatedUser:
        del token
        raise AuthenticationError


class UnavailableVerifier:
    async def verify(self, token: str) -> AuthenticatedUser:
        del token
        raise AuthenticationServiceUnavailableError


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_auth_me_requires_authorization_header() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


@pytest.mark.anyio
@pytest.mark.parametrize("authorization", ["Basic malformed", "Bearer"])
async def test_auth_me_rejects_malformed_bearer_credentials(authorization: str) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/auth/me",
            headers={"Authorization": authorization},
        )

    assert response.status_code == 401


@pytest.mark.anyio
async def test_auth_me_rejects_an_invalid_token() -> None:
    app.dependency_overrides[get_token_verifier] = RejectingVerifier
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer invalid-token"},
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or expired authentication token"}


@pytest.mark.anyio
async def test_auth_me_reports_an_unavailable_identity_provider() -> None:
    app.dependency_overrides[get_token_verifier] = UnavailableVerifier
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer test-access-token"},
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "Authentication service is temporarily unavailable"}


@pytest.mark.anyio
async def test_auth_me_returns_verified_identity() -> None:
    app.dependency_overrides[get_token_verifier] = AcceptingVerifier
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer test-access-token"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "user_id": "10000000-0000-0000-0000-000000000001",
        "email": "verified-user@example.test",
    }
