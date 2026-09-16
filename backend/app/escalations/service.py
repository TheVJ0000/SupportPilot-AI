import asyncio
from uuid import UUID

from pydantic import ValidationError

from app.ai.triage.base import TriageAgent
from app.ai.triage.errors import TriageAgentError
from app.ai.triage.models import TriageErrorCode, TriageToolCall
from app.escalations.context import build_triage_context
from app.escalations.gateway import EscalationGateway
from app.escalations.models import BegunEscalationTriage
from app.escalations.tools import execute_triage_tool


class EscalationTriageService:
    def __init__(self, gateway: EscalationGateway, agent: TriageAgent | None) -> None:
        self._gateway = gateway
        self._agent = agent

    async def _fail_safely(self, begun: BegunEscalationTriage, code: TriageErrorCode) -> None:
        if begun.triage_run_id is None:
            return
        try:
            await self._gateway.fail_triage(begun.escalation_id, begun.triage_run_id, code)
        except Exception:
            # The durable placeholder and stale-recovery guard survive storage/network failure.
            return

    async def triage(self, escalation_id: UUID) -> None:
        try:
            begun = await self._gateway.begin_triage(escalation_id)
        except Exception:
            return
        if not begun.should_run:
            return
        try:
            if self._agent is None:
                raise TriageAgentError("triage_not_configured")
            context = build_triage_context(begun.trigger_reason, begun.messages)
            call = await self._agent.decide_escalation(context)
            try:
                call = TriageToolCall.model_validate(call)
                # Revalidate argument types and extra fields for other provider implementations too.
                call = TriageToolCall.model_validate(call.model_dump())
            except (TypeError, ValueError, ValidationError):
                raise TriageAgentError("triage_invalid_tool_call") from None
            await execute_triage_tool(
                call,
                escalation_id=begun.escalation_id,
                run_id=begun.triage_run_id,
                gateway=self._gateway,
                provider=self._agent.provider_name,
                model=self._agent.model_name,
            )
        except asyncio.CancelledError:
            failure = asyncio.create_task(self._fail_safely(begun, "triage_failed"))
            try:
                await asyncio.shield(failure)
            except asyncio.CancelledError:
                pass
            raise
        except TriageAgentError as error:
            await self._fail_safely(begun, error.code)
        except Exception:
            await self._fail_safely(begun, "triage_failed")
