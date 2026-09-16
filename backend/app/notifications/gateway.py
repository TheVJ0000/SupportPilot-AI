from typing import Any, Literal, Protocol
from uuid import UUID

import httpx

from app.notifications.models import EscalationNotification, NotificationErrorCode

type NotificationRpc = Literal[
    "list_recoverable_escalation_notifications",
    "begin_escalation_notification",
    "complete_escalation_notification",
    "fail_escalation_notification",
]
ALLOWED_NOTIFICATION_RPCS = frozenset(
    {
        "list_recoverable_escalation_notifications",
        "begin_escalation_notification",
        "complete_escalation_notification",
        "fail_escalation_notification",
    }
)


class NotificationGatewayError(Exception):
    def __init__(self) -> None:
        super().__init__("Notification storage is temporarily unavailable.")


class NotificationGateway(Protocol):
    async def begin(self, notification_id: UUID) -> EscalationNotification | None: ...

    async def complete(
        self, notification: EscalationNotification, provider: str, message_id: str
    ) -> None: ...

    async def fail(
        self, notification: EscalationNotification, code: NotificationErrorCode
    ) -> None: ...


class SupabaseNotificationGateway:
    def __init__(self, supabase_url: str, secret_key: str, client: httpx.AsyncClient) -> None:
        if not supabase_url or not secret_key:
            raise ValueError("Invalid notification storage configuration")
        self._base_url = supabase_url.rstrip("/")
        self._client = client
        self._headers = {
            "apikey": secret_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def _rpc(self, name: NotificationRpc, payload: dict[str, Any]) -> object:
        if name not in ALLOWED_NOTIFICATION_RPCS:
            raise NotificationGatewayError()
        try:
            response = await self._client.post(
                f"{self._base_url}/rest/v1/rpc/{name}", headers=self._headers, json=payload
            )
            if response.status_code >= 400:
                raise NotificationGatewayError()
            return response.json()
        except (httpx.RequestError, ValueError):
            raise NotificationGatewayError() from None

    async def list_recoverable(self, max_results: int) -> list[UUID]:
        if not 1 <= max_results <= 20:
            raise NotificationGatewayError()
        result = await self._rpc(
            "list_recoverable_escalation_notifications", {"max_results": max_results}
        )
        try:
            if not isinstance(result, list) or len(result) > max_results:
                raise ValueError()
            return list(dict.fromkeys(UUID(item) for item in result))
        except (TypeError, ValueError, AttributeError):
            raise NotificationGatewayError() from None

    async def begin(self, notification_id: UUID) -> EscalationNotification | None:
        result = await self._rpc(
            "begin_escalation_notification", {"target_notification_id": str(notification_id)}
        )
        if result is None:
            return None
        try:
            notification = EscalationNotification.model_validate(result)
            if notification.notification_id != notification_id:
                raise ValueError()
            return notification
        except (TypeError, ValueError):
            raise NotificationGatewayError() from None

    async def complete(
        self, notification: EscalationNotification, provider: str, message_id: str
    ) -> None:
        result = await self._rpc(
            "complete_escalation_notification",
            {
                "target_notification_id": str(notification.notification_id),
                "expected_attempt_number": notification.attempt_number,
                "submitted_provider": provider,
                "submitted_provider_message_id": message_id,
            },
        )
        if result is not True:
            raise NotificationGatewayError()

    async def fail(self, notification: EscalationNotification, code: NotificationErrorCode) -> None:
        result = await self._rpc(
            "fail_escalation_notification",
            {
                "target_notification_id": str(notification.notification_id),
                "expected_attempt_number": notification.attempt_number,
                "submitted_error_code": code,
            },
        )
        if result is not True:
            raise NotificationGatewayError()
