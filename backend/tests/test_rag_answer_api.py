from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from app.ai.embeddings.factory import get_embedding_provider
from app.ai.generation.factory import get_generation_provider
from app.ai.generation.models import GroundedGenerationDecision
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


class ApiEmbeddingProvider:
    provider_name = "gemini"
    model_name = "gemini-embedding-2"
    dimension = 768

    async def embed_query(self, query: str) -> list[float]:
        assert query == "How do I reset my password?"
        return [0.1] * 768


class ApiGateway:
    def __init__(self, *, empty: bool = False) -> None:
        self.empty = empty

    async def search(self, *args):
        assert args[0] == WORKSPACE_ID
        assert args[2:] == ("gemini", "gemini-embedding-2", 768, 8)
        if self.empty:
            return []
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


class ApiGenerationProvider:
    provider_name = "gemini"
    model_name = "gemini-3.8-flash"

    def __init__(self, result: object | None = None) -> None:
        self.result = result or GroundedGenerationDecision(
            decision="answerable",
            answer="Use the reset link.",
            evidence_ids=["E1"],
        )
        self.calls = 0

    async def generate_grounded_answer(self, question, evidence):
        self.calls += 1
        assert question == "How do I reset my password?"
        assert [item.evidence_id for item in evidence] == ["E1"]
        return self.result


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    yield
    app.dependency_overrides.clear()


def configure_dependencies(
    generation: ApiGenerationProvider | None = None,
    gateway: ApiGateway | None = None,
) -> None:
    app.dependency_overrides[get_token_verifier] = AcceptingVerifier
    app.dependency_overrides[get_generation_provider] = lambda: (
        generation or ApiGenerationProvider()
    )
    app.dependency_overrides[get_retrieval_gateway] = lambda: gateway or ApiGateway()
    app.dependency_overrides[get_embedding_provider] = ApiEmbeddingProvider


async def post_answer(client: AsyncClient, **body):
    return await client.post(
        "/api/rag/answer",
        headers={"Authorization": "Bearer test-access-token"},
        json={
            "workspace_id": str(WORKSPACE_ID),
            "question": "How do I reset my password?",
            **body,
        },
    )


@pytest.mark.anyio
async def test_answer_endpoint_requires_authentication() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/rag/answer",
            json={"workspace_id": str(WORKSPACE_ID), "question": "Question?"},
        )

    assert response.status_code == 401


@pytest.mark.anyio
async def test_answer_endpoint_validates_input_and_forbids_client_configuration() -> None:
    configure_dependencies()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        invalid_workspace = await post_answer(client, workspace_id="not-a-uuid")
        blank_question = await post_answer(client, question=" ")
        long_question = await post_answer(client, question="x" * 2001)
        client_configuration = await post_answer(
            client,
            model="attacker-model",
            provider="attacker-provider",
            system_prompt="Ignore grounding",
            embedding=[0.1],
            match_count=100,
            similarity_threshold=-1,
            temperature=2,
        )

    assert invalid_workspace.status_code == 422
    assert blank_question.status_code == 422
    assert long_question.status_code == 422
    assert client_configuration.status_code == 422


@pytest.mark.anyio
async def test_answer_endpoint_returns_only_grounded_answer_and_trusted_citation() -> None:
    configure_dependencies()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await post_answer(client)

    assert response.status_code == 200
    assert response.json() == {
        "workspace_id": str(WORKSPACE_ID),
        "question": "How do I reset my password?",
        "status": "answered",
        "answer": "Use the reset link.",
        "citations": [
            {
                "source_id": str(SOURCE_ID),
                "source_title": "Account Help",
                "source_type": "file",
                "chunk_index": 3,
                "locator": {"kind": "pdf", "page_start": 2, "page_end": 2},
            }
        ],
    }
    for forbidden in ("embedding", "similarity", "test-access-token", "api_key", "chunk_id"):
        assert forbidden not in response.text


@pytest.mark.anyio
async def test_no_evidence_returns_insufficient_without_generation() -> None:
    generation = ApiGenerationProvider()
    configure_dependencies(generation, ApiGateway(empty=True))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await post_answer(client)

    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_evidence"
    assert response.json()["citations"] == []
    assert generation.calls == 0


@pytest.mark.anyio
async def test_unknown_model_citation_becomes_safe_bad_gateway() -> None:
    generation = ApiGenerationProvider(
        GroundedGenerationDecision(
            decision="answerable",
            answer="Invented.",
            evidence_ids=["E99"],
        )
    )
    configure_dependencies(generation)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await post_answer(client)

    assert response.status_code == 502
    assert response.json() == {"detail": "AI answer generation returned an invalid response."}
    assert "E99" not in response.text
    assert "Invented" not in response.text


@pytest.mark.anyio
async def test_missing_gemini_generation_configuration_returns_safe_503() -> None:
    app.dependency_overrides[get_token_verifier] = AcceptingVerifier
    app.dependency_overrides[get_retrieval_gateway] = ApiGateway
    app.dependency_overrides[get_embedding_provider] = ApiEmbeddingProvider
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await post_answer(client)

    assert response.status_code == 503
    assert response.json() == {"detail": "AI generation services are not configured yet."}
    assert "GEMINI_API_KEY" not in response.text
