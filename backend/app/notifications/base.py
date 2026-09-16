from typing import Protocol

from app.notifications.models import EscalationNotification


class EscalationNotifier(Protocol):
    provider_name: str

    async def send(self, notification: EscalationNotification) -> str: ...
