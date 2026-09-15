import asyncio
import math
from collections.abc import Awaitable, Callable
from typing import Any

from google import genai
from google.genai import types

from app.ai.embeddings.base import EmbeddingDocument
from app.ai.embeddings.errors import EmbeddingProviderError

DEFAULT_BATCH_SIZE = 24
MAX_RETRIES = 2


class GeminiEmbeddingProvider:
    """Gemini Embedding 2 adapter using its current retrieval-document format."""

    provider_name = "gemini"

    def __init__(
        self,
        api_key: str,
        model_name: str,
        dimension: int,
        *,
        client: Any | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not api_key or not model_name or dimension != 768 or not 16 <= batch_size <= 32:
            raise ValueError("Invalid embedding provider configuration")
        self.model_name = model_name
        self.dimension = dimension
        self._client = client or genai.Client(api_key=api_key)
        self._batch_size = batch_size
        self._sleep = sleep

    @staticmethod
    def _document_content(document: EmbeddingDocument) -> types.Content:
        title = (document.title or "none").replace("|", " ").strip() or "none"
        prepared = f"title: {title} | text: {document.text}"
        return types.Content(parts=[types.Part(text=prepared)])

    @staticmethod
    def _status_code(error: Exception) -> int | None:
        for attribute in ("code", "status_code"):
            value = getattr(error, attribute, None)
            if isinstance(value, int):
                return value
        return None

    @classmethod
    def _map_error(cls, error: Exception) -> tuple[str, bool]:
        code = cls._status_code(error)
        if code in {401, 403}:
            return "embedding_auth_failed", False
        if code == 429:
            return "embedding_rate_limited", True
        if code is not None and (code >= 500 or code == 408):
            return "embedding_provider_unavailable", True
        return "embedding_failed", False

    async def _embed_batch(self, batch: list[EmbeddingDocument]) -> list[list[float]]:
        response: Any = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = await self._client.aio.models.embed_content(
                    model=self.model_name,
                    contents=[self._document_content(document) for document in batch],
                    config=types.EmbedContentConfig(output_dimensionality=self.dimension),
                )
                break
            except Exception as error:
                error_code, transient = self._map_error(error)
                if transient and attempt < MAX_RETRIES:
                    await self._sleep(0.25 * (2**attempt))
                    continue
                raise EmbeddingProviderError(error_code) from None

        embeddings = getattr(response, "embeddings", None)
        if not isinstance(embeddings, list) or len(embeddings) != len(batch):
            raise EmbeddingProviderError("embedding_invalid_response")

        validated: list[list[float]] = []
        for embedding in embeddings:
            values = getattr(embedding, "values", None)
            if not isinstance(values, list) or len(values) != self.dimension:
                raise EmbeddingProviderError("embedding_invalid_response")
            vector: list[float] = []
            for value in values:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise EmbeddingProviderError("embedding_invalid_response")
                numeric_value = float(value)
                if not math.isfinite(numeric_value):
                    raise EmbeddingProviderError("embedding_invalid_response")
                vector.append(numeric_value)
            validated.append(vector)
        return validated

    async def embed_documents(self, documents: list[EmbeddingDocument]) -> list[list[float]]:
        if not documents or any(not document.text.strip() for document in documents):
            raise EmbeddingProviderError("embedding_invalid_response")
        vectors: list[list[float]] = []
        for offset in range(0, len(documents), self._batch_size):
            vectors.extend(await self._embed_batch(documents[offset : offset + self._batch_size]))
        return vectors
