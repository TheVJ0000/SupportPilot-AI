from uuid import UUID

import pytest

from app.ai.embeddings.base import EmbeddingDocument
from app.ai.embeddings.errors import EmbeddingProviderError
from app.knowledge.errors import GatewayError, ProcessingHttpError
from app.knowledge.indexing import KnowledgeIndexingService
from app.knowledge.models import IndexedChunk, IndexingChunk, IndexingSource

SOURCE_ID = UUID("30000000-0000-0000-0000-000000000001")
WORKSPACE_ID = UUID("20000000-0000-0000-0000-000000000001")


class FakeGateway:
    def __init__(self) -> None:
        self.source = IndexingSource(
            SOURCE_ID,
            WORKSPACE_ID,
            "Support guide",
            [IndexingChunk(UUID(int=1), 0, "Synthetic chunk", "a" * 64)],
        )
        self.completed: tuple | None = None
        self.failures: list[tuple[UUID, str]] = []
        self.completion_error: GatewayError | None = None

    async def begin_indexing(self, source_id: UUID) -> IndexingSource:
        assert source_id == SOURCE_ID
        return self.source

    async def complete_indexing(
        self,
        source_id: UUID,
        provider_name: str,
        model_name: str,
        dimension: int,
        chunks: list[IndexedChunk],
    ) -> None:
        if self.completion_error:
            raise self.completion_error
        self.completed = (source_id, provider_name, model_name, dimension, chunks)

    async def fail_indexing(self, source_id: UUID, error_code: str) -> None:
        self.failures.append((source_id, error_code))


class FakeProvider:
    provider_name = "fake"
    model_name = "fake-embedding-model"
    dimension = 768

    def __init__(self, error: EmbeddingProviderError | None = None) -> None:
        self.error = error
        self.documents: list[EmbeddingDocument] = []

    async def embed_documents(self, documents: list[EmbeddingDocument]) -> list[list[float]]:
        self.documents = documents
        if self.error:
            raise self.error
        return [[0.1] * 768 for _ in documents]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_indexing_uses_abstraction_and_completes_ready() -> None:
    gateway = FakeGateway()
    provider = FakeProvider()

    result = await KnowledgeIndexingService(gateway, provider).index(SOURCE_ID)

    assert result.status == "ready"
    assert result.embedding_provider == "fake"
    assert provider.documents == [EmbeddingDocument("Synthetic chunk", "Support guide")]
    assert gateway.completed is not None
    assert gateway.completed[4][0].content_sha256 == "a" * 64


@pytest.mark.anyio
async def test_provider_failure_records_safe_indexing_failure() -> None:
    gateway = FakeGateway()
    provider = FakeProvider(EmbeddingProviderError("embedding_rate_limited"))

    with pytest.raises(ProcessingHttpError) as caught:
        await KnowledgeIndexingService(gateway, provider).index(SOURCE_ID)

    assert caught.value.status_code == 503
    assert gateway.failures == [(SOURCE_ID, "embedding_rate_limited")]


@pytest.mark.anyio
async def test_completion_failure_never_reports_success() -> None:
    gateway = FakeGateway()
    gateway.completion_error = GatewayError("complete_knowledge_indexing", "private detail")

    with pytest.raises(ProcessingHttpError) as caught:
        await KnowledgeIndexingService(gateway, FakeProvider()).index(SOURCE_ID)

    assert caught.value.status_code == 502
    assert "private" not in caught.value.detail
    assert gateway.failures == [(SOURCE_ID, "embedding_failed")]
