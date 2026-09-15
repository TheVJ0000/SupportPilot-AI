from http import HTTPStatus
from uuid import UUID

from app.ai.embeddings.base import EmbeddingDocument, EmbeddingProvider
from app.ai.embeddings.errors import EmbeddingProviderError
from app.knowledge.errors import GatewayError, ProcessingHttpError
from app.knowledge.gateway import KnowledgeGateway
from app.knowledge.models import IndexedChunk, IndexingResult

_SAFE_PROVIDER_MESSAGES = {
    "embedding_auth_failed": "AI indexing credentials were rejected.",
    "embedding_rate_limited": "AI indexing is temporarily busy. Please try again later.",
    "embedding_provider_unavailable": "AI indexing is temporarily unavailable.",
    "embedding_invalid_response": "AI indexing returned an invalid result.",
    "embedding_failed": "The source could not be indexed safely.",
}


class KnowledgeIndexingService:
    def __init__(self, gateway: KnowledgeGateway, provider: EmbeddingProvider) -> None:
        self._gateway = gateway
        self._provider = provider

    async def _record_failure(self, source_id: UUID, error_code: str) -> None:
        try:
            await self._gateway.fail_indexing(source_id, error_code)
        except Exception:
            pass

    async def index(self, source_id: UUID) -> IndexingResult:
        try:
            source = await self._gateway.begin_indexing(source_id)
        except GatewayError as error:
            if error.provider_code == "42501":
                raise ProcessingHttpError(
                    "Knowledge management permission is required.", HTTPStatus.FORBIDDEN
                ) from error
            raise ProcessingHttpError(
                "This source cannot be indexed in its current state.", HTTPStatus.CONFLICT
            ) from error

        try:
            documents = [
                EmbeddingDocument(text=chunk.content, title=source.title) for chunk in source.chunks
            ]
            vectors = await self._provider.embed_documents(documents)
            if len(vectors) != len(source.chunks):
                raise EmbeddingProviderError("embedding_invalid_response")
            indexed_chunks = [
                IndexedChunk(chunk.chunk_index, chunk.content_sha256, vector)
                for chunk, vector in zip(source.chunks, vectors, strict=True)
            ]
            try:
                await self._gateway.complete_indexing(
                    source.source_id,
                    self._provider.provider_name,
                    self._provider.model_name,
                    self._provider.dimension,
                    indexed_chunks,
                )
            except GatewayError as error:
                await self._record_failure(source.source_id, "embedding_failed")
                raise ProcessingHttpError(
                    "Knowledge indexing could not be completed safely.",
                    HTTPStatus.BAD_GATEWAY,
                ) from error
        except ProcessingHttpError:
            raise
        except EmbeddingProviderError as error:
            await self._record_failure(source.source_id, error.error_code)
            status_code = (
                HTTPStatus.SERVICE_UNAVAILABLE
                if error.error_code
                in {
                    "embedding_rate_limited",
                    "embedding_provider_unavailable",
                }
                else HTTPStatus.BAD_GATEWAY
            )
            raise ProcessingHttpError(
                _SAFE_PROVIDER_MESSAGES[error.error_code], status_code
            ) from error
        except Exception as error:
            await self._record_failure(source.source_id, "embedding_failed")
            raise ProcessingHttpError(
                _SAFE_PROVIDER_MESSAGES["embedding_failed"], HTTPStatus.BAD_GATEWAY
            ) from error

        return IndexingResult(
            source_id=source.source_id,
            chunk_count=len(source.chunks),
            embedding_provider=self._provider.provider_name,
            embedding_model=self._provider.model_name,
            embedding_dimension=self._provider.dimension,
        )
