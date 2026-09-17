import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_health_check_returns_service_status() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "supportpilot-api",
    }


@pytest.mark.anyio
async def test_cors_allows_only_the_configured_frontend_origin() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        allowed_response = await client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
        untrusted_response = await client.options(
            "/api/health",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert allowed_response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "POST" in allowed_response.headers["access-control-allow-methods"]
    assert "Authorization" in allowed_response.headers["access-control-allow-headers"]
    assert "access-control-allow-origin" not in untrusted_response.headers


@pytest.mark.anyio
@pytest.mark.parametrize(
    "origin,method,expected_status",
    [
        ("http://localhost:5173", "PUT", 200),
        ("https://untrusted.example", "PUT", 400),
        ("http://localhost:5173", "DELETE", 400),
    ],
)
async def test_customer_feedback_cors_preflight(
    origin: str, method: str, expected_status: int
) -> None:
    """Feedback needs PUT, not unrestricted methods or external origins."""
    path = (
        "/api/chat/conversations/40000000-0000-4000-8000-000000000001"
        "/messages/50000000-0000-4000-8000-000000000001/feedback"
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.options(
            path,
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": "content-type,x-supportpilot-session",
            },
        )
    assert response.status_code == expected_status
    if expected_status == 200:
        assert response.headers["access-control-allow-origin"] == origin
        assert set(response.headers["access-control-allow-methods"].split(", ")) == {
            "GET",
            "POST",
            "PUT",
            "PATCH",
        }
        assert "X-SupportPilot-Session" in response.headers["access-control-allow-headers"]
        assert "access-control-allow-credentials" not in response.headers
    if origin == "https://untrusted.example":
        assert "access-control-allow-origin" not in response.headers
