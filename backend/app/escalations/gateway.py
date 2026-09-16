from typing import Any, Literal, Protocol
from uuid import UUID

import httpx
from pydantic import ValidationError

from app.ai.triage.models import CreateEscalationArguments, TriageErrorCode
from app.escalations.models import BegunEscalationTriage

EscalationRpc = Literal[
    "begin_escalation_triage", "complete_escalation_triage", "fail_escalation_triage"
]
ALLOWED_ESCALATION_RPCS = frozenset(
    {"begin_escalation_triage", "complete_escalation_triage", "fail_escalation_triage"}
)


class EscalationGatewayError(Exception):
    def __init__(self) -> None:
        super().__init__("Escalation triage storage is temporarily unavailable.")


class EscalationGateway(Protocol):
    async def begin_triage(self, escalation_id: UUID) -> BegunEscalationTriage: ...

    async def complete_triage(
        self,
        escalation_id: UUID,
        run_id: UUID,
        arguments: CreateEscalationArguments,
        provider: str,
        model: str,
    ) -> None: ...

    async def fail_triage(
        self,
        escalation_id: UUID,
        run_id: UUID,
        code: TriageErrorCode,
    ) -> None: ...


class SupabaseEscalationGateway:
    """Server-only secret-key access to exactly three scoped RPCs, never generic SQL."""

    def __init__(self, supabase_url: str, secret_key: str, client: httpx.AsyncClient) -> None:
        if not supabase_url or not secret_key:
            raise ValueError("Invalid escalation gateway configuration")
        self._base_url = supabase_url.rstrip("/")
        self._client = client
        self._headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "apikey": secret_key,
        }

    async def _rpc(self, name: EscalationRpc, payload: dict[str, Any]) -> object:
        if name not in ALLOWED_ESCALATION_RPCS:
            raise EscalationGatewayError()
        try:
            response = await self._client.post(
                f"{self._base_url}/rest/v1/rpc/{name}",
                headers=self._headers,
                json=payload,
            )
            if response.status_code >= 400:
                raise EscalationGatewayError()
            return response.json()
        except (httpx.RequestError, ValueError):
            raise EscalationGatewayError() from None

    async def begin_triage(self, escalation_id: UUID) -> BegunEscalationTriage:
        payload = await self._rpc(
            "begin_escalation_triage",
            {
                "target_escalation_id": str(escalation_id),
            },
        )
        try:
            result = BegunEscalationTriage.model_validate(payload)
            if result.escalation_id != escalation_id:
                raise ValueError("Unexpected escalation")
            return result
        except (TypeError, ValueError, ValidationError):
            raise EscalationGatewayError() from None

    async def complete_triage(
        self,
        escalation_id: UUID,
        run_id: UUID,
        arguments: CreateEscalationArguments,
        provider: str,
        model: str,
    ) -> None:
        result = await self._rpc(
            "complete_escalation_triage",
            {
                "target_escalation_id": str(escalation_id),
                "target_triage_run_id": str(run_id),
                "submitted_category": arguments.category,
                "submitted_priority": arguments.priority,
                "submitted_summary": arguments.summary,
                "submitted_provider": provider,
                "submitted_model": model,
            },
        )
        if result is not True:
            raise EscalationGatewayError()

    async def fail_triage(self, escalation_id: UUID, run_id: UUID, code: TriageErrorCode) -> None:
        result = await self._rpc(
            "fail_escalation_triage",
            {
                "target_escalation_id": str(escalation_id),
                "target_triage_run_id": str(run_id),
                "submitted_error_code": code,
            },
        )
        if result is not True:
            raise EscalationGatewayError()
