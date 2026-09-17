from collections.abc import AsyncIterator
from typing import Annotated, Literal, TypeVar
from uuid import UUID

import httpx
from fastapi import Depends, HTTPException
from pydantic import ValidationError

from app.admin.models import (
    ConversationDetail,
    ConversationPage,
    ConversationQuery,
    ConversationResolutionRequest,
    Dashboard,
    EscalationDetail,
    EscalationPage,
    EscalationQuery,
    EscalationStatusRequest,
    SafeModel,
)
from app.auth.dependencies import get_authenticated_context
from app.auth.models import AuthenticatedRequestContext
from app.core.config import Settings, get_settings

Result = TypeVar("Result", bound=SafeModel)
RpcName = Literal[
    "admin_dashboard_snapshot",
    "admin_list_conversations",
    "admin_get_conversation",
    "admin_list_escalations",
    "admin_get_escalation",
    "admin_set_conversation_resolution",
    "admin_set_escalation_status",
]


class AdminOperationsGateway:
    """Fixed support reads and lifecycle writes using a publishable key and caller JWT."""

    def __init__(
        self, supabase_url: str, publishable_key: str, access_token: str, client: httpx.AsyncClient
    ) -> None:
        self._url = supabase_url.rstrip("/")
        self._client = client
        self._headers = {
            "apikey": publishable_key,
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def _read(
        self, name: RpcName, workspace_id: UUID, params: dict, model: type[Result]
    ) -> Result:
        try:
            response = await self._client.post(
                f"{self._url}/rest/v1/rpc/{name}",
                headers=self._headers,
                json={"target_workspace_id": str(workspace_id), **params},
            )
        except httpx.RequestError as error:
            raise HTTPException(503, "Support operations are temporarily unavailable") from error
        if response.status_code >= 400:
            try:
                body = response.json()
                code = body.get("code") if isinstance(body, dict) else None
            except ValueError:
                code = None
            if code == "42501":
                raise HTTPException(403, "Owner or admin access required")
            if code == "P0002":
                raise HTTPException(404, "Support record not found")
            if code == "28000":
                raise HTTPException(401, "Authentication required")
            if code in {"40001", "55000", "22023"} and name in {
                "admin_set_conversation_resolution",
                "admin_set_escalation_status",
            }:
                raise HTTPException(409, "Support record changed or transition conflicts")
            raise HTTPException(502, "Support operations could not be loaded")
        try:
            result = model.model_validate_json(response.content)
            if result.workspace_id != workspace_id:
                raise ValueError("Unexpected workspace")
        except (ValidationError, ValueError) as error:
            raise HTTPException(502, "Support operations returned an invalid response") from error
        return result

    async def dashboard(self, workspace_id: UUID) -> Dashboard:
        return await self._read("admin_dashboard_snapshot", workspace_id, {}, Dashboard)

    @staticmethod
    def _params(query: ConversationQuery | EscalationQuery) -> dict:
        raw = query.model_dump(mode="json")
        return {
            "page_limit"
            if key == "limit"
            else f"{key}_filter"
            if key in {"status", "triage_status", "priority", "trigger_reason"}
            else key: value
            for key, value in raw.items()
        }

    @staticmethod
    def _check_page(
        page: ConversationPage | EscalationPage, query: ConversationQuery | EscalationQuery
    ) -> None:
        if len(page.items) > query.limit or (
            page.next_cursor is not None and len(page.items) != query.limit
        ):
            raise HTTPException(502, "Support operations returned an invalid response")
        for item in page.items:
            for name in ("status", "triage_status", "priority", "trigger_reason"):
                expected = getattr(query, name, "all")
                if expected != "all" and getattr(item, name, None) != expected:
                    raise HTTPException(502, "Support operations returned an invalid response")
            if query.cursor_id is not None:
                timestamp = (
                    item.last_message_at if isinstance(page, ConversationPage) else item.created_at
                )
                if query.cursor_time is None:
                    valid = timestamp is None and item.id.int < query.cursor_id.int
                else:
                    valid = timestamp is None or (timestamp, item.id.int) < (
                        query.cursor_time,
                        query.cursor_id.int,
                    )
                if not valid:
                    raise HTTPException(502, "Support operations returned an invalid response")

    async def conversations(self, workspace_id: UUID, query: ConversationQuery) -> ConversationPage:
        page = await self._read(
            "admin_list_conversations", workspace_id, self._params(query), ConversationPage
        )
        self._check_page(page, query)
        return page

    async def escalations(self, workspace_id: UUID, query: EscalationQuery) -> EscalationPage:
        page = await self._read(
            "admin_list_escalations", workspace_id, self._params(query), EscalationPage
        )
        self._check_page(page, query)
        return page

    async def conversation(self, workspace_id: UUID, conversation_id: UUID) -> ConversationDetail:
        result = await self._read(
            "admin_get_conversation",
            workspace_id,
            {"target_conversation_id": str(conversation_id)},
            ConversationDetail,
        )
        if result.conversation.id != conversation_id:
            raise HTTPException(502, "Support operations returned an invalid response")
        return result

    async def escalation(self, workspace_id: UUID, escalation_id: UUID) -> EscalationDetail:
        result = await self._read(
            "admin_get_escalation",
            workspace_id,
            {"target_escalation_id": str(escalation_id)},
            EscalationDetail,
        )
        if result.escalation.id != escalation_id:
            raise HTTPException(502, "Support operations returned an invalid response")
        return result

    async def set_conversation_resolution(
        self, workspace_id: UUID, conversation_id: UUID, request: ConversationResolutionRequest
    ) -> ConversationDetail:
        result = await self._read(
            "admin_set_conversation_resolution",
            workspace_id,
            {
                "target_conversation_id": str(conversation_id),
                "expected_status": request.expected_status,
                "expected_resolution_outcome": request.expected_resolution_outcome,
                "requested_action": request.action,
            },
            ConversationDetail,
        )
        record = result.conversation
        expected_outcome = {
            "resolve": "resolved",
            "close_unresolved": "closed_unresolved",
            "reopen": "unresolved",
        }[request.action]
        expected_status = (
            ("human_requested" if record.human_requested_at is not None else "open")
            if request.action == "reopen"
            else "closed"
        )
        if (
            record.id != conversation_id
            or record.resolution_outcome != expected_outcome
            or record.status != expected_status
        ):
            raise HTTPException(502, "Support operations returned an invalid response")
        return result

    async def set_escalation_status(
        self, workspace_id: UUID, escalation_id: UUID, request: EscalationStatusRequest
    ) -> EscalationDetail:
        result = await self._read(
            "admin_set_escalation_status",
            workspace_id,
            {
                "target_escalation_id": str(escalation_id),
                "expected_current_status": request.expected_status,
                "new_status": request.status,
            },
            EscalationDetail,
        )
        if result.escalation.id != escalation_id or result.escalation.status != request.status:
            raise HTTPException(502, "Support operations returned an invalid response")
        return result


async def get_admin_gateway(
    context: Annotated[AuthenticatedRequestContext, Depends(get_authenticated_context)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[AdminOperationsGateway]:
    if settings.supabase_url is None or not settings.supabase_publishable_key:
        raise HTTPException(503, "Support operations are not configured")
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5, read=30, write=10, pool=5), follow_redirects=False
    ) as client:
        yield AdminOperationsGateway(
            str(settings.supabase_url),
            settings.supabase_publishable_key,
            context.access_token,
            client,
        )
