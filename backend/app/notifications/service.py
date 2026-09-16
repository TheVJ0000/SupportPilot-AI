import asyncio
from uuid import UUID

from app.notifications.base import EscalationNotifier
from app.notifications.gateway import NotificationGateway
from app.notifications.models import (
    EscalationNotification,
    NotificationError,
    NotificationErrorCode,
)


class NotificationService:
    def __init__(self, gateway: NotificationGateway, notifier: EscalationNotifier | None) -> None:
        self._gateway = gateway
        self._notifier = notifier

    async def _fail_safely(
        self, notification: EscalationNotification, code: NotificationErrorCode
    ) -> None:
        try:
            await self._gateway.fail(notification, code)
        except Exception:
            pass

    async def deliver(self, notification_id: UUID) -> None:
        if self._notifier is None:
            return
        try:
            notification = await self._gateway.begin(notification_id)
        except Exception:
            return
        if notification is None:
            return
        try:
            message_id = await self._notifier.send(notification)
        except asyncio.CancelledError:
            # Cancellation can follow acceptance. Never assume it means not sent.
            failure = asyncio.create_task(
                self._fail_safely(notification, "notification_delivery_unknown")
            )
            try:
                await asyncio.shield(failure)
            except asyncio.CancelledError:
                pass
            raise
        except NotificationError as error:
            await self._fail_safely(notification, error.code)
            return
        except Exception:
            await self._fail_safely(notification, "notification_delivery_unknown")
            return
        try:
            await self._gateway.complete(notification, self._notifier.provider_name, message_id)
        except asyncio.CancelledError:
            failure = asyncio.create_task(
                self._fail_safely(notification, "notification_delivery_unknown")
            )
            try:
                await asyncio.shield(failure)
            except asyncio.CancelledError:
                pass
            raise
        except Exception:
            # A lost DB completion response may already be committed; fail is fenced
            # and cannot change sent. If not committed, stop ambiguous long retries.
            await self._fail_safely(notification, "notification_delivery_unknown")
