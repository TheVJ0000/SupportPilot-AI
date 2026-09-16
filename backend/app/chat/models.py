from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator

from app.rag.answering import PreparedGroundedEvidence
from app.rag.models import TrustedCitation


class CustomerSessionResponse(BaseModel):
    conversation_id: UUID
    session_token: str
    workspace_name: str
    expires_at: AwareDatetime


class CustomerTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_message_id: UUID
    message: str


class CustomerTurnResponse(BaseModel):
    conversation_id: UUID
    turn_id: UUID
    message_id: UUID
    client_message_id: UUID
    status: Literal["answered", "insufficient_evidence"]
    answer: str
    citations: list[TrustedCitation]
    is_replay: bool


class CustomerHistoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    role: Literal["customer", "assistant"]
    content: str
    answer_status: Literal["answered", "insufficient_evidence"] | None = None
    created_at: AwareDatetime
    citations: list[TrustedCitation]
    feedback: Literal["positive", "negative"] | None = None

    @model_validator(mode="after")
    def validate_role_state(self) -> Self:
        if self.role == "customer" and (
            self.answer_status is not None or self.feedback is not None
        ):
            raise ValueError("Customer history state is invalid")
        if self.role == "assistant" and self.answer_status is None:
            raise ValueError("Assistant history state is invalid")
        return self


class CustomerConversationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    status: Literal["open", "human_requested", "closed"]
    human_requested_at: AwareDatetime | None = None
    messages: list[CustomerHistoryMessage]

    @model_validator(mode="after")
    def validate_human_request_state(self) -> Self:
        if self.status == "open" and self.human_requested_at is not None:
            raise ValueError("Open conversation state is invalid")
        if self.status == "human_requested" and self.human_requested_at is None:
            raise ValueError("Human-requested conversation state is invalid")
        return self


class CustomerFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rating: Literal["positive", "negative"]


class CustomerFeedbackResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: UUID
    rating: Literal["positive", "negative"]


class CustomerHumanRequestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    status: Literal["human_requested"]
    human_requested_at: AwareDatetime


class CustomerHumanRequestResult(CustomerHumanRequestResponse):
    """Trusted orchestration metadata, never returned to anonymous customers."""

    escalation_id: UUID
    triage_status: Literal["pending", "processing", "completed", "failed"]


class CreatedCustomerSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_session_id: UUID
    conversation_id: UUID
    workspace_id: UUID
    workspace_name: str
    expires_at: AwareDatetime


class StartedCustomerTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: UUID
    workspace_id: UUID
    conversation_id: UUID
    turn_status: Literal["processing", "completed"]
    is_replay: bool


class PersistedCustomerTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: UUID
    conversation_id: UUID
    message_id: UUID
    client_message_id: UUID
    answer_status: Literal["answered", "insufficient_evidence"]
    answer: str
    citations: list[TrustedCitation]


@dataclass(frozen=True)
class CustomerSessionCredential:
    """Request-scoped hash; the raw customer token is deliberately discarded."""

    token_hash: str = field(repr=False)


@dataclass(frozen=True)
class CustomerChatSessionResult:
    conversation_id: UUID
    session_token: str = field(repr=False)
    workspace_name: str
    expires_at: datetime


@dataclass(frozen=True)
class PreparedCustomerTurnStream:
    started: StartedCustomerTurn
    client_message_id: UUID
    question: str
    grounded_evidence: PreparedGroundedEvidence | None
    replay_result: CustomerTurnResponse | None = None


@dataclass(frozen=True)
class CustomerStreamStarted:
    conversation_id: UUID
    turn_id: UUID
    client_message_id: UUID


@dataclass(frozen=True)
class CustomerStreamDelta:
    text: str


@dataclass(frozen=True)
class CustomerStreamComplete:
    result: CustomerTurnResponse


@dataclass(frozen=True)
class CustomerStreamError:
    code: Literal["stream_failed"] = "stream_failed"
    message: str = "I couldn't complete that response right now."


type CustomerTurnStreamEvent = (
    CustomerStreamStarted | CustomerStreamDelta | CustomerStreamComplete | CustomerStreamError
)
