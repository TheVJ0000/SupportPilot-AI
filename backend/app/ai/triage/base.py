from typing import Protocol

from app.ai.triage.models import TriageContext, TriageToolCall


class TriageAgent(Protocol):
    provider_name: str
    model_name: str

    async def decide_escalation(self, context: TriageContext) -> TriageToolCall: ...

    async def aclose(self) -> None: ...
