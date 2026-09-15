from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.ai.generation.base import GenerationProvider
from app.ai.generation.gemini import GeminiGenerationProvider
from app.core.config import Settings, get_settings


def get_generation_provider(
    settings: Annotated[Settings, Depends(get_settings)],
) -> GenerationProvider:
    if settings.gemini_api_key is None or not settings.gemini_generation_model.strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI generation services are not configured yet.",
        )
    return GeminiGenerationProvider(
        api_key=settings.gemini_api_key.get_secret_value(),
        model_name=settings.gemini_generation_model,
    )
