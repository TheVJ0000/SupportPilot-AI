from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.admin.gateway import AdminOperationsGateway, get_admin_gateway
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
)

router = APIRouter(prefix="/admin/workspaces/{workspace_id}", tags=["admin operations"])
Gateway = Annotated[AdminOperationsGateway, Depends(get_admin_gateway)]


@router.get("/dashboard", response_model=Dashboard)
async def dashboard(workspace_id: UUID, gateway: Gateway) -> Dashboard:
    return await gateway.dashboard(workspace_id)


@router.get("/conversations", response_model=ConversationPage)
async def conversations(
    workspace_id: UUID, gateway: Gateway, query: Annotated[ConversationQuery, Query()]
) -> ConversationPage:
    return await gateway.conversations(workspace_id, query)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def conversation(
    workspace_id: UUID, conversation_id: UUID, gateway: Gateway
) -> ConversationDetail:
    return await gateway.conversation(workspace_id, conversation_id)


@router.get("/escalations", response_model=EscalationPage)
async def escalations(
    workspace_id: UUID, gateway: Gateway, query: Annotated[EscalationQuery, Query()]
) -> EscalationPage:
    return await gateway.escalations(workspace_id, query)


@router.get("/escalations/{escalation_id}", response_model=EscalationDetail)
async def escalation(workspace_id: UUID, escalation_id: UUID, gateway: Gateway) -> EscalationDetail:
    return await gateway.escalation(workspace_id, escalation_id)


@router.patch("/conversations/{conversation_id}/resolution", response_model=ConversationDetail)
async def conversation_resolution(
    workspace_id: UUID,
    conversation_id: UUID,
    request: ConversationResolutionRequest,
    gateway: Gateway,
) -> ConversationDetail:
    return await gateway.set_conversation_resolution(workspace_id, conversation_id, request)


@router.patch("/escalations/{escalation_id}/status", response_model=EscalationDetail)
async def escalation_status(
    workspace_id: UUID, escalation_id: UUID, request: EscalationStatusRequest, gateway: Gateway
) -> EscalationDetail:
    return await gateway.set_escalation_status(workspace_id, escalation_id, request)
