import math
import unicodedata
from http import HTTPStatus
from uuid import UUID

from app.ai.embeddings.base import EmbeddingProvider
from app.ai.embeddings.errors import EmbeddingProviderError
from app.knowledge.errors import GatewayError
from app.rag.errors import RetrievalHttpError
from app.rag.gateway import RetrievalGateway
from app.rag.models import RetrievalMatch, RetrievalResponse

MIN_QUERY_CHARS = 2
MAX_QUERY_CHARS = 2000
DEFAULT_MATCH_COUNT = 8

_PROVIDER_MESSAGES = {
    "embedding_auth_failed": "AI retrieval credentials were rejected.",
    "embedding_rate_limited": "AI retrieval is temporarily busy. Please try again later.",
    "embedding_provider_unavailable": "AI retrieval is temporarily unavailable.",
    "embedding_invalid_response": "AI retrieval returned an invalid embedding.",
    "embedding_failed": "The question could not be embedded safely.",
}


def normalize_question(question: str, *, minimum_chars: int = MIN_QUERY_CHARS) -> str:
    if minimum_chars not in {1, MIN_QUERY_CHARS}:
        raise ValueError("Unsupported minimum question length")
    if any(
        unicodedata.category(character) in {"Cc", "Cf"} and character not in {"\t", "\n", "\r"}
        for character in question
    ):
        raise RetrievalHttpError("The question contains unsupported control characters.")
    normalized = " ".join(unicodedata.normalize("NFC", question).split())
    if len(normalized) < minimum_chars:
        noun = "character" if minimum_chars == 1 else "characters"
        raise RetrievalHttpError(f"Enter a question with at least {minimum_chars} {noun}.")
    if len(normalized) > MAX_QUERY_CHARS:
        raise RetrievalHttpError("Questions may contain at most 2,000 characters.")
    return normalized


def validate_query_vector(vector: object, dimension: int) -> list[float]:
    if not isinstance(vector, list) or len(vector) != dimension:
        raise EmbeddingProviderError("embedding_invalid_response")
    validated: list[float] = []
    for value in vector:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise EmbeddingProviderError("embedding_invalid_response")
        numeric_value = float(value)
        if not math.isfinite(numeric_value):
            raise EmbeddingProviderError("embedding_invalid_response")
        validated.append(numeric_value)
    return validated


class KnowledgeRetrievalService:
    def __init__(
        self,
        gateway: RetrievalGateway,
        provider: EmbeddingProvider,
        *,
        minimum_query_chars: int = MIN_QUERY_CHARS,
    ) -> None:
        if minimum_query_chars not in {1, MIN_QUERY_CHARS}:
            raise ValueError("Unsupported minimum query length")
        self._gateway = gateway
        self._provider = provider
        self._minimum_query_chars = minimum_query_chars

    async def retrieve(self, workspace_id: UUID, question: str) -> RetrievalResponse:
        normalized_question = normalize_question(
            question,
            minimum_chars=self._minimum_query_chars,
        )
        try:
            query_vector = validate_query_vector(
                await self._provider.embed_query(normalized_question),
                self._provider.dimension,
            )
        except EmbeddingProviderError as error:
            status_code = (
                HTTPStatus.SERVICE_UNAVAILABLE
                if error.error_code
                in {
                    "embedding_auth_failed",
                    "embedding_rate_limited",
                    "embedding_provider_unavailable",
                }
                else HTTPStatus.BAD_GATEWAY
            )
            raise RetrievalHttpError(_PROVIDER_MESSAGES[error.error_code], status_code) from error
        except Exception as error:
            raise RetrievalHttpError(
                "The question could not be embedded safely.", HTTPStatus.BAD_GATEWAY
            ) from error

        try:
            matches = await self._gateway.search(
                workspace_id,
                query_vector,
                self._provider.provider_name,
                self._provider.model_name,
                self._provider.dimension,
                DEFAULT_MATCH_COUNT,
            )
        except GatewayError as error:
            if error.provider_code == "42501":
                raise RetrievalHttpError(
                    "Workspace access is required for knowledge retrieval.",
                    HTTPStatus.FORBIDDEN,
                ) from error
            raise RetrievalHttpError(
                "Knowledge retrieval is temporarily unavailable.",
                HTTPStatus.BAD_GATEWAY,
            ) from error
        except Exception as error:
            raise RetrievalHttpError(
                "Knowledge retrieval is temporarily unavailable.",
                HTTPStatus.BAD_GATEWAY,
            ) from error

        return RetrievalResponse(
            workspace_id=workspace_id,
            question=normalized_question,
            matches=[RetrievalMatch(**match.__dict__) for match in matches],
        )
