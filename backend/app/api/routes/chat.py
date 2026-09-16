import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.ai.embeddings.base import EmbeddingProvider
from app.ai.embeddings.factory import get_embedding_provider
from app.ai.generation.base import GenerationProvider
from app.ai.generation.factory import get_generation_provider
from app.chat.errors import CustomerChatHttpError
from app.chat.gateway import CustomerChatGateway, get_customer_chat_gateway
from app.chat.models import (
    CustomerConversationResponse,
    CustomerFeedbackRequest,
    CustomerFeedbackResponse,
    CustomerHumanRequestResponse,
    CustomerSessionCredential,
    CustomerSessionResponse,
    CustomerStreamComplete,
    CustomerStreamDelta,
    CustomerStreamError,
    CustomerStreamStarted,
    CustomerTurnRequest,
    CustomerTurnResponse,
    CustomerTurnStreamEvent,
)
from app.chat.security import get_customer_session_credential
from app.chat.service import CustomerChatService
from app.escalations.background import BackgroundTriageRunner, get_background_triage_runner

router = APIRouter(prefix="/chat", tags=["customer-chat"])


def serialize_customer_sse_event(event: CustomerTurnStreamEvent) -> bytes:
    """Serialize one safe JSON payload into one blank-line-delimited SSE frame."""

    if isinstance(event, CustomerStreamStarted):
        event_name = "started"
        payload = {
            "conversation_id": str(event.conversation_id),
            "turn_id": str(event.turn_id),
            "client_message_id": str(event.client_message_id),
        }
    elif isinstance(event, CustomerStreamDelta):
        event_name = "delta"
        payload = {"text": event.text}
    elif isinstance(event, CustomerStreamComplete):
        event_name = "complete"
        payload = event.result.model_dump(mode="json")
    elif isinstance(event, CustomerStreamError):
        event_name = "error"
        payload = {"code": event.code, "message": event.message}
    else:
        raise ValueError("Unknown customer stream event")
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event_name}\ndata: {data}\n\n".encode()


@router.post("/{public_id}/session", response_model=CustomerSessionResponse)
async def create_customer_session(
    public_id: UUID,
    gateway: Annotated[CustomerChatGateway, Depends(get_customer_chat_gateway)],
) -> CustomerSessionResponse:
    try:
        result = await CustomerChatService(gateway).create_session(public_id)
    except CustomerChatHttpError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    return CustomerSessionResponse(
        conversation_id=result.conversation_id,
        session_token=result.session_token,
        workspace_name=result.workspace_name,
        expires_at=result.expires_at,
    )


@router.post("/conversations/{conversation_id}/turns", response_model=CustomerTurnResponse)
async def create_customer_turn(
    conversation_id: UUID,
    request: CustomerTurnRequest,
    credential: Annotated[CustomerSessionCredential, Depends(get_customer_session_credential)],
    gateway: Annotated[CustomerChatGateway, Depends(get_customer_chat_gateway)],
    embedding_provider: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
    generation_provider: Annotated[GenerationProvider, Depends(get_generation_provider)],
) -> CustomerTurnResponse:
    try:
        return await CustomerChatService(
            gateway,
            embedding_provider=embedding_provider,
            generation_provider=generation_provider,
        ).submit_turn(
            conversation_id,
            credential.token_hash,
            request.client_message_id,
            request.message,
        )
    except CustomerChatHttpError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


@router.post("/conversations/{conversation_id}/turns/stream")
async def stream_customer_turn(
    conversation_id: UUID,
    request: CustomerTurnRequest,
    credential: Annotated[CustomerSessionCredential, Depends(get_customer_session_credential)],
    gateway: Annotated[CustomerChatGateway, Depends(get_customer_chat_gateway)],
    embedding_provider: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
    generation_provider: Annotated[GenerationProvider, Depends(get_generation_provider)],
) -> StreamingResponse:
    service = CustomerChatService(
        gateway,
        embedding_provider=embedding_provider,
        generation_provider=generation_provider,
    )
    try:
        prepared = await service.prepare_turn_stream(
            conversation_id,
            credential.token_hash,
            request.client_message_id,
            request.message,
        )
    except CustomerChatHttpError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error

    async def event_stream():
        async for event in service.stream_prepared_turn(prepared, credential.token_hash):
            yield serialize_customer_sse_event(event)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=CustomerConversationResponse,
    response_model_exclude_none=True,
)
async def get_customer_conversation(
    conversation_id: UUID,
    credential: Annotated[CustomerSessionCredential, Depends(get_customer_session_credential)],
    gateway: Annotated[CustomerChatGateway, Depends(get_customer_chat_gateway)],
) -> CustomerConversationResponse:
    try:
        return await CustomerChatService(gateway).get_conversation(
            conversation_id,
            credential.token_hash,
        )
    except CustomerChatHttpError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


@router.put(
    "/conversations/{conversation_id}/messages/{message_id}/feedback",
    response_model=CustomerFeedbackResponse,
)
async def set_customer_message_feedback(
    conversation_id: UUID,
    message_id: UUID,
    request: CustomerFeedbackRequest,
    credential: Annotated[CustomerSessionCredential, Depends(get_customer_session_credential)],
    gateway: Annotated[CustomerChatGateway, Depends(get_customer_chat_gateway)],
) -> CustomerFeedbackResponse:
    try:
        return await CustomerChatService(gateway).set_feedback(
            conversation_id,
            credential.token_hash,
            message_id,
            request.rating,
        )
    except CustomerChatHttpError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


@router.post(
    "/conversations/{conversation_id}/human-request",
    response_model=CustomerHumanRequestResponse,
)
async def request_customer_human_support(
    conversation_id: UUID,
    background_tasks: BackgroundTasks,
    credential: Annotated[CustomerSessionCredential, Depends(get_customer_session_credential)],
    gateway: Annotated[CustomerChatGateway, Depends(get_customer_chat_gateway)],
    triage_runner: Annotated[BackgroundTriageRunner, Depends(get_background_triage_runner)],
) -> CustomerHumanRequestResponse:
    try:
        result = await CustomerChatService(gateway).request_human_support(
            conversation_id,
            credential.token_hash,
        )
    except CustomerChatHttpError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    background_tasks.add_task(triage_runner, result.escalation_id)
    return CustomerHumanRequestResponse(
        conversation_id=result.conversation_id,
        status=result.status,
        human_requested_at=result.human_requested_at,
    )
