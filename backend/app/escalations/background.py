from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import Depends

from app.ai.triage.factory import create_triage_agent
from app.chat.gateway import REQUEST_TIMEOUT
from app.core.config import Settings, get_settings
from app.escalations.gateway import SupabaseEscalationGateway
from app.escalations.service import EscalationTriageService

type BackgroundTriageRunner = Callable[[UUID], Awaitable[None]]


def get_background_triage_runner(
    settings: Annotated[Settings, Depends(get_settings)],
) -> BackgroundTriageRunner:
    async def run(escalation_id: UUID) -> None:
        # Own clients here: request-scoped resources may already be closed after the response.
        if settings.supabase_url is None or settings.supabase_secret_key is None:
            return
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=False) as client:
                gateway = SupabaseEscalationGateway(
                    str(settings.supabase_url),
                    settings.supabase_secret_key.get_secret_value(),
                    client,
                )
                agent = None
                try:
                    try:
                        agent = create_triage_agent(settings)
                    except (TypeError, ValueError):
                        # Invalid optional AI configuration must not prevent safe failure recording.
                        agent = None
                    await EscalationTriageService(gateway, agent).triage(escalation_id)
                finally:
                    if agent is not None:
                        await agent.aclose()
        except Exception:
            # Never turn a committed human request into a customer-facing AI error.
            return

    return run
