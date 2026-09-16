from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ai.triage.models import TriageMessage


class BegunEscalationTriage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    escalation_id: UUID
    workspace_id: UUID
    conversation_id: UUID
    trigger_reason: Literal["human_requested", "insufficient_evidence"]
    triage_status: Literal["pending", "processing", "completed", "failed"]
    should_run: bool
    triage_run_id: UUID | None = None
    attempt_number: int = Field(ge=0)
    messages: list[TriageMessage] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_run(self) -> Self:
        if self.should_run and (
            self.triage_status != "processing"
            or self.triage_run_id is None
            or self.attempt_number < 1
        ):
            raise ValueError("Invalid triage attempt")
        if not self.should_run and (self.messages or self.triage_run_id is not None):
            raise ValueError("Inactive triage cannot carry a transcript or run")
        return self
