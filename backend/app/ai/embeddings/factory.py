from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.ai.embeddings.base import EmbeddingProvider
from app.ai.embeddings.gemini import GeminiEmbeddingProvider
from app.core.config import Settings, get_settings


def get_embedding_provider(
    settings: Annotated[Settings, Depends(get_settings)],
) -> EmbeddingProvider:
    if settings.gemini_api_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI embedding services are not configured yet.",
        )
    return GeminiEmbeddingProvider(
        api_key=settings.gemini_api_key.get_secret_value(),
        model_name=settings.gemini_embedding_model,
        dimension=settings.gemini_embedding_dimension,
    )
