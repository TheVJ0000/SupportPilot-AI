from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from app.ai.embeddings.factory import get_embedding_provider
from app.auth.dependencies import get_token_verifier
from app.auth.models import AuthenticatedUser
from app.core.config import Settings, get_settings
from app.main import app
from app.rag.gateway import get_retrieval_gateway
from app.rag.models import RetrievedChunk

WORKSPACE_ID = UUID("20000000-0000-0000-0000-000000000001")
SOURCE_ID = UUID("30000000-0000-0000-0000-000000000001")
CHUNK_ID = UUID("40000000-0000-0000-0000-000000000001")


class AcceptingVerifier:
    async def verify(self, token: str) -> AuthenticatedUser:
        assert token == "test-access-token"
        return AuthenticatedUser(user_id=UUID("10000000-0000-0000-0000-000000000001"))


class ApiProvider:
    provider_name = "gemini"
    model_name = "gemini-embedding-2"
    dimension = 768

    async def embed_query(self, query: str) -> list[float]:
        assert query == "How do I reset my password?"
        return [0.1] * 768


class ApiGateway:
    async def search(self, *args):
        assert args[0] == WORKSPACE_ID
        assert args[2:] == ("gemini", "gemini-embedding-2", 768, 8)
        return [
            RetrievedChunk(
                CHUNK_ID,
                SOURCE_ID,
                "Account Help",
                "file",
                3,
                "Use the reset link.",
                {"kind": "pdf", "page_start": 2, "page_end": 2},
                0.84,
            )
        ]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_retrieval_endpoint_requires_authentication() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/rag/retrieve",
            json={"workspace_id": str(WORKSPACE_ID), "question": "Synthetic question"},
        )
    assert response.status_code == 401


@pytest.mark.anyio
async def test_retrieval_endpoint_validates_workspace_uuid_and_question() -> None:
    app.dependency_overrides[get_token_verifier] = AcceptingVerifier
    app.dependency_overrides[get_retrieval_gateway] = ApiGateway
    app.dependency_overrides[get_embedding_provider] = ApiProvider
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        invalid_workspace = await client.post(
            "/api/rag/retrieve",
            headers={"Authorization": "Bearer test-access-token"},
            json={"workspace_id": "not-a-uuid", "question": "Synthetic question"},
        )
        blank_question = await client.post(
            "/api/rag/retrieve",
            headers={"Authorization": "Bearer test-access-token"},
            json={"workspace_id": str(WORKSPACE_ID), "question": " "},
        )
        long_question = await client.post(
            "/api/rag/retrieve",
            headers={"Authorization": "Bearer test-access-token"},
            json={"workspace_id": str(WORKSPACE_ID), "question": "x" * 2001},
        )

    assert invalid_workspace.status_code == 422
    assert blank_question.status_code == 422
    assert long_question.status_code == 422


@pytest.mark.anyio
async def test_retrieval_response_contains_ranked_evidence_but_no_vector_or_secret() -> None:
    app.dependency_overrides[get_token_verifier] = AcceptingVerifier
    app.dependency_overrides[get_retrieval_gateway] = ApiGateway
    app.dependency_overrides[get_embedding_provider] = ApiProvider
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/rag/retrieve",
            headers={"Authorization": "Bearer test-access-token"},
            json={
                "workspace_id": str(WORKSPACE_ID),
                "question": "How do I reset my password?",
            },
        )

    assert response.status_code == 200
    assert response.json()["matches"][0] == {
        "chunk_id": str(CHUNK_ID),
        "source_id": str(SOURCE_ID),
        "source_title": "Account Help",
        "source_type": "file",
        "chunk_index": 3,
        "content": "Use the reset link.",
        "locator": {"kind": "pdf", "page_start": 2, "page_end": 2},
        "similarity": 0.84,
    }
    assert "embedding" not in response.text
    assert "test-access-token" not in response.text


@pytest.mark.anyio
async def test_client_cannot_select_embedding_or_match_settings() -> None:
    app.dependency_overrides[get_token_verifier] = AcceptingVerifier
    app.dependency_overrides[get_retrieval_gateway] = ApiGateway
    app.dependency_overrides[get_embedding_provider] = ApiProvider
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/rag/retrieve",
            headers={"Authorization": "Bearer test-access-token"},
            json={
                "workspace_id": str(WORKSPACE_ID),
                "question": "Synthetic question",
                "provider": "attacker",
                "dimension": 3,
                "match_count": 1000,
            },
        )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_missing_gemini_configuration_returns_safe_503() -> None:
    app.dependency_overrides[get_token_verifier] = AcceptingVerifier
    app.dependency_overrides[get_retrieval_gateway] = ApiGateway
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/rag/retrieve",
            headers={"Authorization": "Bearer test-access-token"},
            json={"workspace_id": str(WORKSPACE_ID), "question": "Synthetic question"},
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "AI embedding services are not configured yet."}
    assert "GEMINI_API_KEY" not in response.text
