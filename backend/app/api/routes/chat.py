from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.ai.embeddings.base import EmbeddingProvider
from app.ai.embeddings.factory import get_embedding_provider
from app.ai.generation.base import GenerationProvider
from app.ai.generation.factory import get_generation_provider
from app.chat.errors import CustomerChatHttpError
from app.chat.gateway import CustomerChatGateway, get_customer_chat_gateway
from app.chat.models import (
    CustomerConversationResponse,
    CustomerSessionCredential,
    CustomerSessionResponse,
    CustomerTurnRequest,
    CustomerTurnResponse,
)
from app.chat.security import get_customer_session_credential
from app.chat.service import CustomerChatService

router = APIRouter(prefix="/chat", tags=["customer-chat"])


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
