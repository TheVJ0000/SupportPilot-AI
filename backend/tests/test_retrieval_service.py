from uuid import UUID

import pytest

from app.ai.embeddings.errors import EmbeddingProviderError
from app.knowledge.errors import GatewayError
from app.rag.errors import RetrievalHttpError
from app.rag.models import RetrievedChunk
from app.rag.service import DEFAULT_MATCH_COUNT, KnowledgeRetrievalService

WORKSPACE_ID = UUID("20000000-0000-0000-0000-000000000001")
SOURCE_ID = UUID("30000000-0000-0000-0000-000000000001")
CHUNK_ID = UUID("40000000-0000-0000-0000-000000000001")


class FakeProvider:
    provider_name = "gemini"
    model_name = "gemini-embedding-2"
    dimension = 768

    def __init__(self, vector=None, error: EmbeddingProviderError | None = None) -> None:
        self.vector = vector if vector is not None else [0.1] * 768
        self.error = error
        self.queries: list[str] = []

    async def embed_query(self, query: str) -> list[float]:
        self.queries.append(query)
        if self.error:
            raise self.error
        return self.vector


class FakeGateway:
    def __init__(self, matches=None, error: GatewayError | None = None) -> None:
        self.matches = matches if matches is not None else []
        self.error = error
        self.calls: list[tuple] = []

    async def search(
        self, workspace_id, query_embedding, provider_name, model_name, dimension, match_count
    ):
        self.calls.append(
            (
                workspace_id,
                query_embedding,
                provider_name,
                model_name,
                dimension,
                match_count,
            )
        )
        if self.error:
            raise self.error
        return self.matches


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_retrieval_normalizes_and_embeds_query_once_with_server_configuration() -> None:
    match = RetrievedChunk(
        CHUNK_ID,
        SOURCE_ID,
        "Account Help",
        "file",
        3,
        "Use the reset link.",
        {"kind": "pdf", "page_start": 2, "page_end": 2},
        0.84,
    )
    provider = FakeProvider()
    gateway = FakeGateway([match])

    result = await KnowledgeRetrievalService(gateway, provider).retrieve(
        WORKSPACE_ID, "  How do I\n reset my password?  "
    )

    assert provider.queries == ["How do I reset my password?"]
    assert gateway.calls == [
        (
            WORKSPACE_ID,
            [0.1] * 768,
            "gemini",
            "gemini-embedding-2",
            768,
            DEFAULT_MATCH_COUNT,
        )
    ]
    assert result.question == "How do I reset my password?"
    assert result.matches[0].locator == {"kind": "pdf", "page_start": 2, "page_end": 2}
    assert result.matches[0].similarity == 0.84


@pytest.mark.anyio
@pytest.mark.parametrize("question", ["", " ", "x", "x" * 2001, "hello\x00world"])
async def test_invalid_questions_are_rejected_before_embedding(question: str) -> None:
    provider = FakeProvider()
    gateway = FakeGateway()

    with pytest.raises(RetrievalHttpError) as caught:
        await KnowledgeRetrievalService(gateway, provider).retrieve(WORKSPACE_ID, question)

    assert caught.value.status_code == 422
    assert provider.queries == []
    assert gateway.calls == []


@pytest.mark.anyio
async def test_empty_evidence_is_a_successful_result() -> None:
    result = await KnowledgeRetrievalService(FakeGateway(), FakeProvider()).retrieve(
        WORKSPACE_ID, "Where is the synthetic guide?"
    )
    assert result.matches == []


@pytest.mark.anyio
async def test_provider_unavailable_is_mapped_safely() -> None:
    provider = FakeProvider(error=EmbeddingProviderError("embedding_provider_unavailable"))

    with pytest.raises(RetrievalHttpError) as caught:
        await KnowledgeRetrievalService(FakeGateway(), provider).retrieve(
            WORKSPACE_ID, "Synthetic question"
        )

    assert caught.value.status_code == 503
    assert "provider" not in caught.value.detail.lower()


@pytest.mark.anyio
async def test_unexpected_provider_detail_is_never_exposed() -> None:
    class UnexpectedProvider(FakeProvider):
        async def embed_query(self, query: str) -> list[float]:
            del query
            raise RuntimeError("secret key and raw provider payload")

    with pytest.raises(RetrievalHttpError) as caught:
        await KnowledgeRetrievalService(FakeGateway(), UnexpectedProvider()).retrieve(
            WORKSPACE_ID, "Synthetic question"
        )

    assert caught.value.status_code == 502
    assert "secret" not in caught.value.detail


@pytest.mark.anyio
async def test_service_rejects_malformed_provider_vector_before_database() -> None:
    gateway = FakeGateway()

    with pytest.raises(RetrievalHttpError) as caught:
        service = KnowledgeRetrievalService(gateway, FakeProvider(vector=[float("nan")] * 768))
        await service.retrieve(WORKSPACE_ID, "Synthetic question")

    assert caught.value.status_code == 502
    assert gateway.calls == []


@pytest.mark.anyio
async def test_database_permission_failure_is_mapped_without_details() -> None:
    gateway = FakeGateway(error=GatewayError("search_knowledge_chunks", "42501"))

    with pytest.raises(RetrievalHttpError) as caught:
        await KnowledgeRetrievalService(gateway, FakeProvider()).retrieve(
            WORKSPACE_ID, "Synthetic question"
        )

    assert caught.value.status_code == 403
    assert "sql" not in caught.value.detail.lower()
