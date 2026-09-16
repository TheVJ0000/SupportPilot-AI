from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

type TriageCategory = Literal[
    "account_access", "billing", "technical", "product", "policy", "cancellation_refund", "other"
]
type TriagePriority = Literal["low", "normal", "high", "urgent"]
type TriageErrorCode = Literal[
    "triage_not_configured",
    "triage_auth_failed",
    "triage_rate_limited",
    "triage_provider_unavailable",
    "triage_invalid_tool_call",
    "triage_failed",
    "stale_triage_recovered",
]
ProviderLabel = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]


class TriageMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    role: Literal["customer", "assistant"]
    content: str = Field(min_length=1, max_length=4000)
    answer_status: Literal["answered", "insufficient_evidence"] | None = None

    @model_validator(mode="after")
    def validate_message(self) -> Self:
        if not self.content.strip():
            raise ValueError("Empty triage message")
        if self.role == "customer" and (len(self.content) > 2000 or self.answer_status is not None):
            raise ValueError("Invalid customer message")
        if self.role == "assistant" and self.answer_status is None:
            raise ValueError("Invalid assistant message")
        return self


class TriageContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    trigger_reason: Literal["human_requested", "insufficient_evidence"]
    conversation: list[TriageMessage] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_budget(self) -> Self:
        if sum(len(message.content) for message in self.conversation) > 12000:
            raise ValueError("Triage context exceeds the safe budget")
        return self


class CreateEscalationArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    category: TriageCategory
    priority: TriagePriority
    summary: str = Field(min_length=1, max_length=1200)

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        summary = value.strip()
        if not summary:
            raise ValueError("Summary must be non-empty")
        return summary


class TriageToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    name: Literal["create_escalation"]
    arguments: CreateEscalationArguments
