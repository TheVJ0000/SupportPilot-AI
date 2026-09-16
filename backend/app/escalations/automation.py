import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from typing import Protocol
from uuid import UUID

import httpx
from fastapi import FastAPI

from app.ai.triage.factory import create_triage_agent
from app.chat.gateway import REQUEST_TIMEOUT
from app.core.config import Settings, get_settings
from app.escalations.gateway import SupabaseEscalationGateway
from app.escalations.service import EscalationTriageService
from app.notifications.gateway import SupabaseNotificationGateway
from app.notifications.resend import create_notifier
from app.notifications.service import NotificationService

POLL_INTERVAL_SECONDS = 60
MAX_AUTOMATION_ITEMS = 10
MAX_AUTOMATION_CONCURRENCY = 2


class RecoveryLister(Protocol):
    async def list_recoverable(self, max_results: int) -> list[UUID]: ...


class EscalationAutomationWorker:
    def __init__(
        self,
        triage_gateway: RecoveryLister,
        triage: Callable[[UUID], Awaitable[None]] | None,
        notification_gateway: RecoveryLister,
        deliver: Callable[[UUID], Awaitable[None]] | None,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._triage_gateway = triage_gateway
        self._triage = triage
        self._notification_gateway = notification_gateway
        self._deliver = deliver
        self._sleep = sleep

    async def _process(
        self, gateway: RecoveryLister, operation: Callable[[UUID], Awaitable[None]] | None
    ) -> None:
        if operation is None:
            return
        try:
            ids = await gateway.list_recoverable(MAX_AUTOMATION_ITEMS)
        except Exception:
            return
        semaphore = asyncio.Semaphore(MAX_AUTOMATION_CONCURRENCY)

        async def run(item: UUID) -> None:
            async with semaphore:
                try:
                    await operation(item)
                except Exception:
                    # Only DB state records safe errors; never log provider payloads.
                    pass

        # Bound even a misbehaving gateway and remove duplicate IDs locally.
        await asyncio.gather(
            *(run(item) for item in list(dict.fromkeys(ids))[:MAX_AUTOMATION_ITEMS])
        )

    async def cycle(self) -> None:
        await self._process(self._triage_gateway, self._triage)
        await self._process(self._notification_gateway, self._deliver)

    async def run(self) -> None:
        while True:
            try:
                await self.cycle()
            except Exception:
                pass
            await self._sleep(POLL_INTERVAL_SECONDS)


@asynccontextmanager
async def automation_context(settings: Settings) -> AsyncIterator[None]:
    if settings.supabase_url is None or settings.supabase_secret_key is None:
        yield
        return
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=False) as client:
        agent = None
        try:
            agent = create_triage_agent(settings)
        except Exception:
            pass
        key = settings.supabase_secret_key.get_secret_value()
        triage_gateway = SupabaseEscalationGateway(str(settings.supabase_url), key, client)
        notification_gateway = SupabaseNotificationGateway(str(settings.supabase_url), key, client)
        notifier = create_notifier(settings, client)
        worker = EscalationAutomationWorker(
            triage_gateway,
            EscalationTriageService(triage_gateway, agent).triage if agent is not None else None,
            notification_gateway,
            NotificationService(notification_gateway, notifier).deliver
            if notifier is not None
            else None,
        )
        task = asyncio.create_task(worker.run(), name="escalation-automation")
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task
            if agent is not None:
                with suppress(Exception):
                    await agent.aclose()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with automation_context(get_settings()):
        yield
