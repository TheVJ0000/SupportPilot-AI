from typing import Protocol

from app.ai.generation.models import GenerationEvidence, GroundedGenerationDecision


class GenerationProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    async def generate_grounded_answer(
        self,
        question: str,
        evidence: list[GenerationEvidence],
    ) -> GroundedGenerationDecision: ...
