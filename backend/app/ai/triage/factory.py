from app.ai.triage.base import TriageAgent
from app.ai.triage.gemini import GeminiTriageAgent
from app.core.config import Settings


def create_triage_agent(settings: Settings) -> TriageAgent | None:
    """Optional provider construction: human requests never depend on an AI key."""
    if settings.gemini_api_key is None or not settings.gemini_triage_model.strip():
        return None
    return GeminiTriageAgent(
        settings.gemini_api_key.get_secret_value(),
        settings.gemini_triage_model,
    )
