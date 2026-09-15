from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict

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


class CustomerConversationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    status: Literal["open", "human_requested", "closed"]
    messages: list[CustomerHistoryMessage]


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
