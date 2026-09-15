from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any, Literal, Protocol
from uuid import UUID

import httpx
from fastapi import Depends, HTTPException, status
from pydantic import ValidationError

from app.chat.errors import CustomerChatGatewayError
from app.chat.models import (
    CreatedCustomerSession,
    CustomerConversationResponse,
    CustomerFeedbackResponse,
    CustomerHumanRequestResponse,
    PersistedCustomerTurn,
    StartedCustomerTurn,
)
from app.core.config import Settings, get_settings
from app.knowledge.errors import GatewayError
from app.rag.gateway import RetrievalGateway, parse_retrieval_rows
from app.rag.models import RetrievedChunk, TrustedCitation

REQUEST_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
CustomerChatRpc = Literal[
    "create_customer_chat_session",
    "begin_customer_chat_turn",
    "get_customer_chat_turn_result",
    "get_customer_conversation",
    "set_customer_message_feedback",
    "request_customer_human_support",
    "search_customer_chat_knowledge",
    "complete_customer_chat_turn",
    "fail_customer_chat_turn",
]
ALLOWED_CUSTOMER_CHAT_RPCS = frozenset(
    {
        "create_customer_chat_session",
        "begin_customer_chat_turn",
        "get_customer_chat_turn_result",
        "get_customer_conversation",
        "set_customer_message_feedback",
        "request_customer_human_support",
        "search_customer_chat_knowledge",
        "complete_customer_chat_turn",
        "fail_customer_chat_turn",
    }
)


class CustomerChatGateway(Protocol):
    async def create_session(
        self,
        public_id: UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> CreatedCustomerSession: ...

    async def begin_turn(
        self,
        conversation_id: UUID,
        token_hash: str,
        client_message_id: UUID,
        message: str,
    ) -> StartedCustomerTurn: ...

    async def get_turn_result(
        self,
        conversation_id: UUID,
        token_hash: str,
        client_message_id: UUID,
    ) -> PersistedCustomerTurn: ...

    async def complete_turn(
        self,
        turn_id: UUID,
        token_hash: str,
        answer_status: str,
        answer: str,
        citations: list[TrustedCitation],
    ) -> None: ...

    async def fail_turn(self, turn_id: UUID, token_hash: str, error_code: str) -> None: ...

    async def get_conversation(
        self,
        conversation_id: UUID,
        token_hash: str,
    ) -> CustomerConversationResponse: ...

    async def set_feedback(
        self,
        conversation_id: UUID,
        token_hash: str,
        message_id: UUID,
        rating: str,
    ) -> CustomerFeedbackResponse: ...

    async def request_human_support(
        self,
        conversation_id: UUID,
        token_hash: str,
    ) -> CustomerHumanRequestResponse: ...

    def retrieval_gateway(
        self,
        conversation_id: UUID,
        token_hash: str,
        workspace_id: UUID,
    ) -> RetrievalGateway: ...


def _single_record(payload: object, operation: str) -> object:
    if isinstance(payload, list):
        if len(payload) != 1:
            raise CustomerChatGatewayError(operation)
        return payload[0]
    return payload


class SupabaseCustomerChatGateway:
    """The only secret-key boundary, limited to explicit customer-chat RPCs."""

    def __init__(
        self,
        supabase_url: str,
        secret_key: str,
        client: httpx.AsyncClient,
    ) -> None:
        if not supabase_url or not secret_key:
            raise ValueError("Invalid customer-chat gateway configuration")
        self._base_url = supabase_url.rstrip("/")
        self._client = client
        self._headers = {
            "Accept": "application/json",
            "apikey": secret_key,
            "Content-Type": "application/json",
        }

    @staticmethod
    def _provider_code(response: httpx.Response) -> str | None:
        try:
            payload = response.json()
        except ValueError:
            return None
        code = payload.get("code") if isinstance(payload, dict) else None
        return code if isinstance(code, str) and len(code) <= 32 else None

    async def _rpc(self, function_name: CustomerChatRpc, payload: dict[str, Any]) -> object:
        if function_name not in ALLOWED_CUSTOMER_CHAT_RPCS:
            raise CustomerChatGatewayError("unsupported_customer_chat_rpc")
        try:
            response = await self._client.post(
                f"{self._base_url}/rest/v1/rpc/{function_name}",
                headers=self._headers,
                json=payload,
            )
        except httpx.RequestError as error:
            raise CustomerChatGatewayError(function_name) from error
        if response.status_code >= 400:
            raise CustomerChatGatewayError(function_name, self._provider_code(response))
        try:
            return response.json()
        except ValueError as error:
            raise CustomerChatGatewayError(function_name) from error

    async def create_session(
        self,
        public_id: UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> CreatedCustomerSession:
        operation = "create_customer_chat_session"
        payload = await self._rpc(
            operation,
            {
                "target_public_id": str(public_id),
                "session_token_hash": token_hash,
                "session_expires_at": expires_at.isoformat(),
            },
        )
        try:
            return CreatedCustomerSession.model_validate(_single_record(payload, operation))
        except (TypeError, ValidationError, ValueError) as error:
            raise CustomerChatGatewayError(operation) from error

    async def begin_turn(
        self,
        conversation_id: UUID,
        token_hash: str,
        client_message_id: UUID,
        message: str,
    ) -> StartedCustomerTurn:
        operation = "begin_customer_chat_turn"
        payload = await self._rpc(
            operation,
            {
                "target_conversation_id": str(conversation_id),
                "session_token_hash": token_hash,
                "target_client_message_id": str(client_message_id),
                "message_content": message,
            },
        )
        try:
            return StartedCustomerTurn.model_validate(_single_record(payload, operation))
        except (TypeError, ValidationError, ValueError) as error:
            raise CustomerChatGatewayError(operation) from error

    async def get_turn_result(
        self,
        conversation_id: UUID,
        token_hash: str,
        client_message_id: UUID,
    ) -> PersistedCustomerTurn:
        operation = "get_customer_chat_turn_result"
        payload = await self._rpc(
            operation,
            {
                "target_conversation_id": str(conversation_id),
                "session_token_hash": token_hash,
                "target_client_message_id": str(client_message_id),
            },
        )
        try:
            return PersistedCustomerTurn.model_validate(_single_record(payload, operation))
        except (TypeError, ValidationError, ValueError) as error:
            raise CustomerChatGatewayError(operation) from error

    async def search_knowledge(
        self,
        conversation_id: UUID,
        token_hash: str,
        query_embedding: list[float],
        provider_name: str,
        model_name: str,
        dimension: int,
        match_count: int,
    ) -> list[RetrievedChunk]:
        operation = "search_customer_chat_knowledge"
        payload = await self._rpc(
            operation,
            {
                "target_conversation_id": str(conversation_id),
                "session_token_hash": token_hash,
                "query_embedding": query_embedding,
                "expected_provider": provider_name,
                "expected_model": model_name,
                "expected_dimension": dimension,
                "match_count": match_count,
            },
        )
        try:
            return parse_retrieval_rows(payload, operation)
        except GatewayError as error:
            raise CustomerChatGatewayError(operation, error.provider_code) from error

    async def complete_turn(
        self,
        turn_id: UUID,
        token_hash: str,
        answer_status: str,
        answer: str,
        citations: list[TrustedCitation],
    ) -> None:
        result = await self._rpc(
            "complete_customer_chat_turn",
            {
                "target_turn_id": str(turn_id),
                "session_token_hash": token_hash,
                "submitted_answer_status": answer_status,
                "answer_content": answer,
                "citation_payload": [citation.model_dump(mode="json") for citation in citations],
            },
        )
        if result is not True:
            raise CustomerChatGatewayError("complete_customer_chat_turn")

    async def fail_turn(self, turn_id: UUID, token_hash: str, error_code: str) -> None:
        result = await self._rpc(
            "fail_customer_chat_turn",
            {
                "target_turn_id": str(turn_id),
                "session_token_hash": token_hash,
                "submitted_error_code": error_code,
            },
        )
        if result is not True:
            raise CustomerChatGatewayError("fail_customer_chat_turn")

    async def get_conversation(
        self,
        conversation_id: UUID,
        token_hash: str,
    ) -> CustomerConversationResponse:
        operation = "get_customer_conversation"
        payload = await self._rpc(
            operation,
            {
                "target_conversation_id": str(conversation_id),
                "session_token_hash": token_hash,
            },
        )
        try:
            return CustomerConversationResponse.model_validate(_single_record(payload, operation))
        except (TypeError, ValidationError, ValueError) as error:
            raise CustomerChatGatewayError(operation) from error

    async def set_feedback(
        self,
        conversation_id: UUID,
        token_hash: str,
        message_id: UUID,
        rating: str,
    ) -> CustomerFeedbackResponse:
        operation = "set_customer_message_feedback"
        payload = await self._rpc(
            operation,
            {
                "target_conversation_id": str(conversation_id),
                "session_token_hash": token_hash,
                "target_message_id": str(message_id),
                "submitted_rating": rating,
            },
        )
        try:
            return CustomerFeedbackResponse.model_validate(_single_record(payload, operation))
        except (TypeError, ValidationError, ValueError) as error:
            raise CustomerChatGatewayError(operation) from error

    async def request_human_support(
        self,
        conversation_id: UUID,
        token_hash: str,
    ) -> CustomerHumanRequestResponse:
        operation = "request_customer_human_support"
        payload = await self._rpc(
            operation,
            {
                "target_conversation_id": str(conversation_id),
                "session_token_hash": token_hash,
            },
        )
        try:
            return CustomerHumanRequestResponse.model_validate(_single_record(payload, operation))
        except (TypeError, ValidationError, ValueError) as error:
            raise CustomerChatGatewayError(operation) from error

    def retrieval_gateway(
        self,
        conversation_id: UUID,
        token_hash: str,
        workspace_id: UUID,
    ) -> RetrievalGateway:
        return CustomerSessionRetrievalGateway(self, conversation_id, token_hash, workspace_id)


class CustomerSessionRetrievalGateway:
    """Adapts the conversation-scoped RPC to the existing retrieval service."""

    def __init__(
        self,
        gateway: SupabaseCustomerChatGateway,
        conversation_id: UUID,
        token_hash: str,
        workspace_id: UUID,
    ) -> None:
        self._gateway = gateway
        self._conversation_id = conversation_id
        self._token_hash = token_hash
        self._workspace_id = workspace_id

    async def search(
        self,
        workspace_id: UUID,
        query_embedding: list[float],
        provider_name: str,
        model_name: str,
        dimension: int,
        match_count: int,
    ) -> list[RetrievedChunk]:
        if workspace_id != self._workspace_id:
            raise GatewayError("search_customer_chat_knowledge")
        try:
            return await self._gateway.search_knowledge(
                self._conversation_id,
                self._token_hash,
                query_embedding,
                provider_name,
                model_name,
                dimension,
                match_count,
            )
        except CustomerChatGatewayError as error:
            raise GatewayError("search_customer_chat_knowledge", error.provider_code) from error


@asynccontextmanager
async def _customer_chat_gateway_context(
    settings: Settings,
) -> AsyncIterator[SupabaseCustomerChatGateway]:
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=False) as client:
        yield SupabaseCustomerChatGateway(
            supabase_url=str(settings.supabase_url),
            secret_key=settings.supabase_secret_key.get_secret_value(),
            client=client,
        )


async def get_customer_chat_gateway(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[CustomerChatGateway]:
    if settings.supabase_url is None or settings.supabase_secret_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Customer chat is not configured yet.",
        )
    async with _customer_chat_gateway_context(settings) as gateway:
        yield gateway
