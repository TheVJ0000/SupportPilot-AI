import asyncio
from collections.abc import Awaitable, Callable

import httpx
from pydantic import SecretStr

from app.core.config import Settings
from app.notifications.models import EMAIL_PATTERN, EscalationNotification, NotificationError

MAX_RETRIES = 2


class ResendEscalationNotifier:
    provider_name = "resend"

    def __init__(
        self,
        api_key: SecretStr,
        sender: str,
        client: httpx.AsyncClient,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if (
            not api_key.get_secret_value().strip()
            or len(sender) > 254
            or EMAIL_PATTERN.fullmatch(sender) is None
        ):
            raise ValueError("Invalid optional notification configuration")
        self._api_key = api_key
        self._sender = sender
        self._client = client
        self._sleep = sleep

    async def send(self, notification: EscalationNotification) -> str:
        category = notification.category.replace("_", " ").title()
        priority = notification.priority.title()
        payload = {
            "from": self._sender,
            "to": notification.recipient_emails[:1],
            "subject": f"[SupportPilot] {priority} priority support escalation",
            "text": (
                f"SupportPilot recorded a support escalation for {notification.workspace_name}.\n\n"
                f"Category: {category}\nPriority: {priority}\n\n"
                "Sign in to SupportPilot to review the conversation and escalation."
            ),
        }
        if len(notification.recipient_emails) > 1:
            # Only trusted managers receive mail; remaining addresses aren't disclosed.
            payload["bcc"] = notification.recipient_emails[1:]
        headers = {
            "Authorization": f"Bearer {self._api_key.get_secret_value()}",
            "Content-Type": "application/json",
            "User-Agent": "SupportPilot-AI/0.1",
            "Idempotency-Key": f"supportpilot-escalation/{notification.notification_id}",
        }
        ambiguous = False
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = await self._client.post(
                    "https://api.resend.com/emails",
                    headers=headers,
                    json=payload,
                    follow_redirects=False,
                )
            except httpx.RequestError as error:
                # Connect failures precede acceptance; read/write timeouts may not.
                ambiguous |= not isinstance(
                    error, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
                )
                if attempt < MAX_RETRIES:
                    await self._sleep(0.25 * 2**attempt)
                    continue
                raise NotificationError(
                    "notification_delivery_unknown"
                    if ambiguous
                    else "notification_provider_unavailable"
                ) from None
            status = response.status_code
            if 200 <= status < 300:
                try:
                    message_id = response.json()["id"]
                    if (
                        not isinstance(message_id, str)
                        or not 1 <= len(message_id) <= 200
                        or message_id != message_id.strip()
                        or not message_id.strip()
                    ):
                        raise ValueError()
                    return message_id
                except (KeyError, TypeError, ValueError):
                    raise NotificationError("notification_delivery_unknown") from None
            if status in (401, 403):
                raise NotificationError("notification_auth_failed") from None
            if status == 409:
                # Changed recipients/copy under the same key or concurrent request:
                # don't invent a fresh key and risk a second email.
                raise NotificationError("notification_delivery_unknown") from None
            if status == 408 or status >= 500 or status == 429:
                ambiguous |= status == 408 or status >= 500
                if attempt < MAX_RETRIES:
                    await self._sleep(0.25 * 2**attempt)
                    continue
                code = "notification_delivery_unknown" if ambiguous else "notification_rate_limited"
                raise NotificationError(code) from None
            raise NotificationError("notification_configuration_invalid") from None
        raise NotificationError("notification_failed")


def create_notifier(
    settings: Settings, client: httpx.AsyncClient
) -> ResendEscalationNotifier | None:
    if settings.resend_api_key is None or settings.resend_from_email is None:
        return None
    try:
        return ResendEscalationNotifier(settings.resend_api_key, settings.resend_from_email, client)
    except ValueError:
        return None
