from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    model_validator,
)

from app.rag.gateway import _valid_locator


def timestamp_input(value: object) -> object:
    # PostgreSQL emits ISO timestamps, never numeric epoch values; don't silently coerce a bad RPC.
    if not isinstance(value, (str, datetime)) or (isinstance(value, str) and "T" not in value):
        raise ValueError("Expected an ISO timestamp")
    return value


Timestamp = Annotated[AwareDatetime, BeforeValidator(timestamp_input)]

Count = Annotated[int, Field(strict=True, ge=0)]
ConversationStatus = Literal["open", "human_requested", "closed"]
ResolutionOutcome = Literal["unresolved", "resolved", "closed_unresolved"]
ResolutionAction = Literal["resolve", "close_unresolved", "reopen"]
EscalationStatus = Literal["open", "in_progress", "resolved", "closed"]
TriageStatus = Literal["pending", "processing", "completed", "failed"]
Priority = Literal["low", "normal", "high", "urgent"]
TriggerReason = Literal["human_requested", "insufficient_evidence"]
Category = Literal[
    "account_access", "billing", "technical", "product", "policy", "cancellation_refund", "other"
]
TriageError = Literal[
    "triage_not_configured",
    "triage_auth_failed",
    "triage_rate_limited",
    "triage_provider_unavailable",
    "triage_invalid_tool_call",
    "triage_failed",
    "stale_triage_recovered",
]
NotificationStatus = Literal["pending", "sending", "sent", "failed"]
NotificationError = Literal[
    "notification_configuration_invalid",
    "notification_auth_failed",
    "notification_rate_limited",
    "notification_provider_unavailable",
    "notification_failed",
    "notification_no_recipients",
    "notification_delivery_unknown",
    "stale_notification_recovered",
]
ProviderName = Annotated[str, Field(strict=True, min_length=1, max_length=100)]


class SafeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Metrics(SafeModel):
    total_conversations: Count
    resolved_conversations: Count
    closed_unresolved_conversations: Count
    ai_answered_conversations: Count
    insufficient_evidence_conversations: Count
    escalated_conversations: Count
    human_requested_conversations: Count
    positive_feedback_count: Count
    negative_feedback_count: Count
    open_escalations: Count
    high_priority_escalations: Count
    urgent_escalations: Count
    knowledge_ready: Count
    knowledge_processing: Count
    knowledge_failed: Count

    @model_validator(mode="after")
    def conversation_counts(self) -> Self:
        for count in (
            self.resolved_conversations,
            self.closed_unresolved_conversations,
            self.ai_answered_conversations,
            self.insufficient_evidence_conversations,
            self.escalated_conversations,
            self.human_requested_conversations,
        ):
            if count > self.total_conversations:
                raise ValueError("Inconsistent conversation counts")
        if (
            self.resolved_conversations + self.closed_unresolved_conversations
            > self.total_conversations
        ):
            raise ValueError("Inconsistent resolution counts")
        return self


class ConversationMetadata(SafeModel):
    id: UUID
    status: ConversationStatus
    resolution_outcome: ResolutionOutcome
    created_at: Timestamp
    updated_at: Timestamp
    last_message_at: Timestamp | None

    @model_validator(mode="after")
    def outcome(self) -> Self:
        if (self.status == "closed") == (self.resolution_outcome == "unresolved"):
            raise ValueError("Inconsistent conversation outcome")
        return self


class ConversationItem(ConversationMetadata):
    message_count: Count
    assistant_message_count: Count
    feedback_positive_count: Count
    feedback_negative_count: Count
    has_escalation: StrictBool
    escalation_priority: Priority | None

    @model_validator(mode="after")
    def counts(self) -> Self:
        if (
            self.assistant_message_count > self.message_count
            or self.feedback_positive_count + self.feedback_negative_count
            > self.assistant_message_count
            or (not self.has_escalation and self.escalation_priority is not None)
        ):
            raise ValueError("Inconsistent conversation record")
        return self


class ConversationRecord(ConversationMetadata):
    human_requested_at: Timestamp | None
    resolved_at: Timestamp | None
    closed_at: Timestamp | None

    @model_validator(mode="after")
    def resolution_times(self) -> Self:
        if (self.status == "closed") != (self.closed_at is not None):
            raise ValueError("Invalid closure timestamp")
        if (self.resolution_outcome == "resolved") != (self.resolved_at is not None):
            raise ValueError("Invalid resolution timestamp")
        if self.resolved_at is not None and self.resolved_at != self.closed_at:
            raise ValueError("Inconsistent resolution timestamps")
        return self


class ConversationResolutionRequest(SafeModel):
    expected_status: ConversationStatus
    expected_resolution_outcome: ResolutionOutcome
    action: ResolutionAction


class EscalationStatusRequest(SafeModel):
    expected_status: EscalationStatus
    status: EscalationStatus


class EscalationOverview(SafeModel):
    id: UUID
    conversation_id: UUID
    trigger_reason: TriggerReason
    status: EscalationStatus
    triage_status: TriageStatus
    category: Category | None
    priority: Priority | None
    created_at: Timestamp
    triaged_at: Timestamp | None

    @model_validator(mode="after")
    def classification(self) -> Self:
        classified = all(
            value is not None for value in (self.category, self.priority, self.triaged_at)
        )
        if self.triage_status == "completed":
            if not classified:
                raise ValueError("Missing completed classification")
        elif any(value is not None for value in (self.category, self.priority, self.triaged_at)):
            raise ValueError("Unexpected classification")
        return self


class EscalationItem(EscalationOverview):
    summary: Annotated[str, Field(strict=True, min_length=1, max_length=1200)] | None
    triage_attempts: Count
    updated_at: Timestamp
    last_error_code: TriageError | None
    notification_status: NotificationStatus | None

    @model_validator(mode="after")
    def state(self) -> Self:
        if self.triage_status == "completed" and (
            self.summary is None or self.triage_attempts < 1 or self.last_error_code is not None
        ):
            raise ValueError("Invalid completed triage")
        if self.triage_status != "completed" and self.summary is not None:
            raise ValueError("Unexpected summary")
        if (self.triage_status == "failed") != (self.last_error_code is not None):
            raise ValueError("Invalid triage error state")
        return self


class Cursor(SafeModel):
    time: Timestamp | None
    id: UUID


def validate_page(items: list, cursor: Cursor | None, time_field: str) -> None:
    keys = [(getattr(item, time_field), item.id.int) for item in items]
    sorted_keys = sorted(
        keys, key=lambda key: (key[0] is not None, key[0] or 0, key[1]), reverse=True
    )
    if keys != sorted_keys or len({item.id for item in items}) != len(items):
        raise ValueError("Invalid page ordering")
    if cursor is not None and (not items or (cursor.time, cursor.id.int) != keys[-1]):
        raise ValueError("Invalid page cursor")


class ConversationPage(SafeModel):
    workspace_id: UUID
    items: list[ConversationItem] = Field(max_length=50)
    next_cursor: Cursor | None

    @model_validator(mode="after")
    def page(self) -> Self:
        validate_page(self.items, self.next_cursor, "last_message_at")
        return self


class EscalationPage(SafeModel):
    workspace_id: UUID
    items: list[EscalationItem] = Field(max_length=50)
    next_cursor: Cursor | None

    @model_validator(mode="after")
    def page(self) -> Self:
        validate_page(self.items, self.next_cursor, "created_at")
        return self


class Dashboard(SafeModel):
    workspace_id: UUID
    metrics: Metrics
    recent_conversations: list[ConversationItem] = Field(max_length=5)
    recent_escalations: list[EscalationOverview] = Field(max_length=5)

    @model_validator(mode="after")
    def ordering(self) -> Self:
        validate_page(self.recent_conversations, None, "last_message_at")
        validate_page(self.recent_escalations, None, "created_at")
        return self


class Citation(SafeModel):
    source_id: UUID
    source_title: Annotated[str, Field(strict=True, min_length=1, max_length=200)]
    source_type: Literal["file", "faq"]
    chunk_index: Count
    locator: dict

    @model_validator(mode="after")
    def location(self) -> Self:
        if not _valid_locator(self.locator) or (self.source_type == "faq") != (
            self.locator["kind"] == "faq"
        ):
            raise ValueError("Invalid citation location")
        return self


class Message(SafeModel):
    id: UUID
    role: Literal["customer", "assistant"]
    content: Annotated[str, Field(strict=True, min_length=1, max_length=4000)]
    answer_status: Literal["answered", "insufficient_evidence"] | None
    created_at: Timestamp
    feedback: Literal["positive", "negative"] | None
    citations: list[Citation] = Field(max_length=8)

    @model_validator(mode="after")
    def role_data(self) -> Self:
        if not self.content.strip() or (self.role == "customer" and len(self.content) > 2000):
            raise ValueError("Invalid message content")
        if self.role == "customer" and (
            self.answer_status is not None or self.feedback is not None or self.citations
        ):
            raise ValueError("Unexpected customer answer data")
        if self.role == "assistant" and self.answer_status is None:
            raise ValueError("Missing assistant answer status")
        return self


class ConversationDetail(SafeModel):
    workspace_id: UUID
    conversation: ConversationRecord
    messages: list[Message] = Field(max_length=200)
    escalation: EscalationItem | None

    @model_validator(mode="after")
    def association(self) -> Self:
        if self.escalation is not None and self.escalation.conversation_id != self.conversation.id:
            raise ValueError("Invalid escalation association")
        if len({message.id for message in self.messages}) != len(self.messages):
            raise ValueError("Duplicate message")
        return self


class AuditRun(SafeModel):
    attempt_number: Annotated[int, Field(strict=True, ge=1)]
    status: Literal["processing", "completed", "failed"]
    provider: ProviderName | None
    model: ProviderName | None
    tool_name: Literal["create_escalation"] | None
    safe_error_code: TriageError | None
    started_at: Timestamp
    completed_at: Timestamp | None

    @model_validator(mode="after")
    def state(self) -> Self:
        if self.status == "completed" and (
            not self.provider
            or not self.model
            or not self.tool_name
            or self.safe_error_code is not None
        ):
            raise ValueError("Invalid completed audit")
        if self.status != "completed" and any(
            value is not None for value in (self.provider, self.model, self.tool_name)
        ):
            raise ValueError("Unexpected audit provider")
        if (self.status == "failed") != (self.safe_error_code is not None):
            raise ValueError("Invalid audit error")
        if (self.status == "processing") != (self.completed_at is None):
            raise ValueError("Invalid audit completion")
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("Invalid audit timestamps")
        return self


class Notification(SafeModel):
    status: NotificationStatus
    attempts: Count
    provider: ProviderName | None
    last_error_code: NotificationError | None
    sent_at: Timestamp | None
    created_at: Timestamp
    updated_at: Timestamp

    @model_validator(mode="after")
    def delivery(self) -> Self:
        if (self.status == "sent") != (self.sent_at is not None and self.provider is not None):
            raise ValueError("Invalid notification delivery")
        if self.status != "sent" and (self.sent_at is not None or self.provider is not None):
            raise ValueError("Unexpected delivery metadata")
        if (self.status == "failed") != (self.last_error_code is not None):
            raise ValueError("Invalid notification error")
        if (self.status == "pending" and self.attempts != 0) or (
            self.status != "pending" and self.attempts < 1
        ):
            raise ValueError("Invalid notification attempts")
        return self


class EscalationDetail(SafeModel):
    workspace_id: UUID
    escalation: EscalationItem
    audit_runs: list[AuditRun] = Field(max_length=50)
    notification: Notification | None

    @model_validator(mode="after")
    def audit_order(self) -> Self:
        attempts = [run.attempt_number for run in self.audit_runs]
        if attempts != sorted(set(attempts), reverse=True) or any(
            attempt > self.escalation.triage_attempts for attempt in attempts
        ):
            raise ValueError("Invalid audit ordering")
        if (
            self.notification.status if self.notification else None
        ) != self.escalation.notification_status:
            raise ValueError("Inconsistent notification status")
        return self


class ConversationQuery(SafeModel):
    limit: int = Field(default=25, ge=1, le=50)
    status: Literal["all", "open", "human_requested", "closed"] = "all"
    cursor_time: Timestamp | None = None
    cursor_id: UUID | None = None

    @model_validator(mode="after")
    def cursor(self) -> Self:
        if self.cursor_time is not None and self.cursor_id is None:
            raise ValueError("Cursor time requires an ID")
        return self


class EscalationQuery(SafeModel):
    limit: int = Field(default=25, ge=1, le=50)
    status: Literal["all", "open", "in_progress", "resolved", "closed"] = "all"
    triage_status: Literal["all", "pending", "processing", "completed", "failed"] = "all"
    priority: Literal["all", "low", "normal", "high", "urgent"] = "all"
    trigger_reason: Literal["all", "human_requested", "insufficient_evidence"] = "all"
    cursor_time: Timestamp | None = None
    cursor_id: UUID | None = None

    @model_validator(mode="after")
    def cursor(self) -> Self:
        if (self.cursor_time is None) != (self.cursor_id is None):
            raise ValueError("Escalation cursor requires time and ID")
        return self
