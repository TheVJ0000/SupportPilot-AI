import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ai.triage.models import TriageCategory, TriagePriority

type NotificationErrorCode = Literal[
    "notification_auth_failed",
    "notification_configuration_invalid",
    "notification_rate_limited",
    "notification_provider_unavailable",
    "notification_no_recipients",
    "notification_delivery_unknown",
    "notification_failed",
    "stale_notification_recovered",
]
EMAIL_PATTERN = re.compile(r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$")


class EscalationNotification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    notification_id: UUID
    workspace_name: str = Field(min_length=1, max_length=100)
    category: TriageCategory
    priority: TriagePriority
    recipient_emails: list[str] = Field(min_length=1, max_length=20, repr=False)
    attempt_number: int = Field(ge=1, le=3)

    @field_validator("recipient_emails")
    @classmethod
    def valid_emails(cls, values: list[str]) -> list[str]:
        if any(len(value) > 254 or EMAIL_PATTERN.fullmatch(value) is None for value in values):
            raise ValueError("Invalid notification recipients")
        return sorted(set(values))


class NotificationError(Exception):
    def __init__(self, code: NotificationErrorCode) -> None:
        self.code = code
        super().__init__("Notification delivery could not be confirmed safely.")
