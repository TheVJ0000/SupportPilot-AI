from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from app.ai.embeddings.factory import get_embedding_provider
from app.auth.dependencies import get_token_verifier
from app.auth.models import AuthenticatedUser
from app.core.config import Settings, get_settings
from app.knowledge.gateway import get_knowledge_gateway
from app.knowledge.models import IndexedChunk, IndexingChunk, IndexingSource
from app.main import app

SOURCE_ID = UUID("30000000-0000-0000-0000-000000000001")
WORKSPACE_ID = UUID("20000000-0000-0000-0000-000000000001")


class AcceptingVerifier:
    async def verify(self, token: str) -> AuthenticatedUser:
        assert token == "test-access-token"
        return AuthenticatedUser(user_id=UUID("10000000-0000-0000-0000-000000000001"))


class ApiGateway:
    def __init__(self) -> None:
        self.source_ids: list[UUID] = []

    async def begin_indexing(self, source_id: UUID) -> IndexingSource:
        self.source_ids.append(source_id)
        return IndexingSource(
            source_id,
            WORKSPACE_ID,
            "Synthetic guide",
            [IndexingChunk(UUID(int=1), 0, "Synthetic content", "b" * 64)],
        )

    async def complete_indexing(
        self,
        source_id: UUID,
        provider_name: str,
        model_name: str,
        dimension: int,
        chunks: list[IndexedChunk],
    ) -> None:
        assert source_id == SOURCE_ID
        assert (provider_name, model_name, dimension) == ("fake", "fake-model", 768)
        assert len(chunks) == 1

    async def fail_indexing(self, source_id: UUID, error_code: str) -> None:
        raise AssertionError(f"Unexpected failure: {source_id} {error_code}")


class ApiProvider:
    provider_name = "fake"
    model_name = "fake-model"
    dimension = 768

    async def embed_documents(self, documents):
        assert len(documents) == 1
        return [[0.2] * 768]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_indexing_endpoint_requires_authentication() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/knowledge/{SOURCE_ID}/index")
    assert response.status_code == 401


@pytest.mark.anyio
async def test_indexing_accepts_only_source_id_and_returns_no_vectors_or_secrets() -> None:
    gateway = ApiGateway()
    app.dependency_overrides[get_token_verifier] = AcceptingVerifier
    app.dependency_overrides[get_knowledge_gateway] = lambda: gateway
    app.dependency_overrides[get_embedding_provider] = ApiProvider
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/knowledge/{SOURCE_ID}/index",
            headers={"Authorization": "Bearer test-access-token"},
            json={"provider": "attacker", "model": "attacker", "embedding": [1, 2]},
        )

    assert response.status_code == 200
    assert gateway.source_ids == [SOURCE_ID]
    assert response.json() == {
        "source_id": str(SOURCE_ID),
        "status": "ready",
        "chunk_count": 1,
        "embedding_provider": "fake",
        "embedding_model": "fake-model",
        "embedding_dimension": 768,
    }
    assert "test-access-token" not in response.text
    assert 'embedding"' not in response.text


@pytest.mark.anyio
async def test_missing_gemini_configuration_is_safe_and_does_not_crash_app() -> None:
    app.dependency_overrides[get_token_verifier] = AcceptingVerifier
    app.dependency_overrides[get_knowledge_gateway] = lambda: ApiGateway()
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/knowledge/{SOURCE_ID}/index",
            headers={"Authorization": "Bearer test-access-token"},
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "AI indexing is not configured yet."}
    assert "GEMINI_API_KEY" not in response.text
