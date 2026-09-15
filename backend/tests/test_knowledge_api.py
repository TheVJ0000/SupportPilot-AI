from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.dependencies import get_token_verifier
from app.auth.models import AuthenticatedUser
from app.auth.verifier import AuthenticationError
from app.knowledge.gateway import get_knowledge_gateway
from app.knowledge.models import KnowledgeChunk, ProcessingSource
from app.main import app

SOURCE_ID = UUID("30000000-0000-0000-0000-000000000001")
WORKSPACE_ID = UUID("20000000-0000-0000-0000-000000000001")


class AcceptingVerifier:
    async def verify(self, token: str) -> AuthenticatedUser:
        assert token == "test-access-token"
        return AuthenticatedUser(user_id=UUID("10000000-0000-0000-0000-000000000001"))


class RejectingVerifier:
    async def verify(self, token: str) -> AuthenticatedUser:
        del token
        raise AuthenticationError


class ApiGateway:
    def __init__(self) -> None:
        self.source_ids: list[UUID] = []

    async def begin_extraction(self, source_id: UUID) -> ProcessingSource:
        self.source_ids.append(source_id)
        return ProcessingSource(
            source_id=source_id,
            workspace_id=WORKSPACE_ID,
            source_type="faq",
            storage_path=None,
            original_filename=None,
            mime_type=None,
            byte_size=None,
            faq_question="What is the support window?",
            faq_answer="The synthetic support window is nine to five.",
        )

    async def download_source(self, storage_path: str) -> bytes:
        raise AssertionError(f"Unexpected download: {storage_path}")

    async def complete_extraction(
        self, source_id: UUID, chunks: list[KnowledgeChunk], extracted_char_count: int
    ) -> None:
        assert source_id == SOURCE_ID
        assert chunks
        assert extracted_char_count > 0

    async def fail_extraction(self, source_id: UUID, error_code: str) -> None:
        raise AssertionError(f"Unexpected failure: {source_id} {error_code}")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_processing_endpoint_requires_bearer_token() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/knowledge/{SOURCE_ID}/process")

    assert response.status_code == 401


@pytest.mark.anyio
async def test_processing_endpoint_rejects_invalid_token_through_existing_auth() -> None:
    app.dependency_overrides[get_token_verifier] = RejectingVerifier
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/knowledge/{SOURCE_ID}/process",
            headers={"Authorization": "Bearer invalid-token"},
        )

    assert response.status_code == 401


@pytest.mark.anyio
async def test_processing_endpoint_accepts_only_path_source_id_and_returns_no_token() -> None:
    gateway = ApiGateway()
    app.dependency_overrides[get_token_verifier] = AcceptingVerifier
    app.dependency_overrides[get_knowledge_gateway] = lambda: gateway
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/knowledge/{SOURCE_ID}/process",
            headers={"Authorization": "Bearer test-access-token"},
            json={
                "workspace_id": "attacker-controlled",
                "storage_path": "other/private/path",
                "user_id": "attacker-controlled",
            },
        )

    assert response.status_code == 200
    assert gateway.source_ids == [SOURCE_ID]
    assert response.json()["source_id"] == str(SOURCE_ID)
    assert response.json()["status"] == "pending"
    assert response.json()["next_stage"] == "embedding"
    assert "test-access-token" not in response.text
