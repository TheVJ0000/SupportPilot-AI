import json
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
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
    CustomerTurnRequest,
    CustomerTurnResponse,
)
from app.chat.security import get_customer_session_credential
from app.chat.service import CustomerChatService

router = APIRouter(prefix="/chat", tags=["customer-chat"])

STREAM_CHUNK_CHARS = 48


def _answer_chunks(answer: str) -> list[str]:
    """Split a completed grounded answer without breaking words where practical."""
    chunks: list[str] = []
    remaining = answer
    while remaining:
        if len(remaining) <= STREAM_CHUNK_CHARS:
            chunks.append(remaining)
            break
        boundary = remaining.rfind(" ", 0, STREAM_CHUNK_CHARS + 1)
        if boundary <= 0:
            boundary = STREAM_CHUNK_CHARS
        else:
            boundary += 1
        chunks.append(remaining[:boundary])
        remaining = remaining[boundary:]
    return chunks


async def _stream_turn(result: CustomerTurnResponse) -> AsyncIterator[str]:
    for chunk in _answer_chunks(result.answer):
        yield json.dumps({"event": "answer_delta", "delta": chunk}) + "\n"
    yield (
        json.dumps(
            {"event": "complete", "result": result.model_dump(mode="json")},
            separators=(",", ":"),
        )
        + "\n"
    )


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
    """Persist a grounded turn, then deliver its answer as validated NDJSON events."""
    try:
        result = await CustomerChatService(
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
    return StreamingResponse(
        _stream_turn(result),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
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
    credential: Annotated[CustomerSessionCredential, Depends(get_customer_session_credential)],
    gateway: Annotated[CustomerChatGateway, Depends(get_customer_chat_gateway)],
) -> CustomerHumanRequestResponse:
    try:
        return await CustomerChatService(gateway).request_human_support(
            conversation_id,
            credential.token_hash,
        )
    except CustomerChatHttpError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
