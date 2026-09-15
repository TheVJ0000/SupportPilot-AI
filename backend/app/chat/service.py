from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from uuid import UUID

from app.ai.embeddings.base import EmbeddingProvider
from app.ai.generation.base import GenerationProvider
from app.chat.context import build_contextual_question
from app.chat.errors import CustomerChatGatewayError, CustomerChatHttpError
from app.chat.gateway import CustomerChatGateway
from app.chat.models import (
    CustomerChatSessionResult,
    CustomerConversationResponse,
    CustomerTurnResponse,
    PersistedCustomerTurn,
)
from app.chat.security import generate_customer_session_token, hash_customer_session_token
from app.rag.answering import RagAnswerService
from app.rag.errors import RagAnswerHttpError, RetrievalHttpError
from app.rag.service import KnowledgeRetrievalService, normalize_question

CUSTOMER_SESSION_TTL = timedelta(days=7)


def _gateway_http_error(error: CustomerChatGatewayError) -> CustomerChatHttpError:
    if error.operation == "create_customer_chat_session" and error.provider_code in {
        "22023",
        "P0002",
    }:
        return CustomerChatHttpError("Customer chat is unavailable.", HTTPStatus.NOT_FOUND)
    if error.provider_code == "28000":
        return CustomerChatHttpError(
            "The customer session is invalid or expired.",
            HTTPStatus.UNAUTHORIZED,
        )
    if error.provider_code == "54000":
        return CustomerChatHttpError(
            "This conversation has reached its message limit.",
            HTTPStatus.CONFLICT,
        )
    if error.provider_code in {"42501", "55000"}:
        return CustomerChatHttpError(
            "The conversation is not available for this request.",
            HTTPStatus.CONFLICT,
        )
    return CustomerChatHttpError(
        "Customer chat is temporarily unavailable.",
        HTTPStatus.BAD_GATEWAY,
    )


def _turn_response(result: PersistedCustomerTurn, *, is_replay: bool) -> CustomerTurnResponse:
    return CustomerTurnResponse(
        conversation_id=result.conversation_id,
        turn_id=result.turn_id,
        client_message_id=result.client_message_id,
        status=result.answer_status,
        answer=result.answer,
        citations=result.citations,
        is_replay=is_replay,
    )


class CustomerChatService:
    def __init__(
        self,
        gateway: CustomerChatGateway,
        *,
        embedding_provider: EmbeddingProvider | None = None,
        generation_provider: GenerationProvider | None = None,
        token_factory: Callable[[], str] = generate_customer_session_token,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._gateway = gateway
        self._embedding_provider = embedding_provider
        self._generation_provider = generation_provider
        self._token_factory = token_factory
        self._clock = clock

    async def create_session(self, public_id: UUID) -> CustomerChatSessionResult:
        raw_token = self._token_factory()
        token_hash = hash_customer_session_token(raw_token)
        expires_at = self._clock() + CUSTOMER_SESSION_TTL
        try:
            created = await self._gateway.create_session(public_id, token_hash, expires_at)
        except CustomerChatGatewayError as error:
            raise _gateway_http_error(error) from error
        return CustomerChatSessionResult(
            conversation_id=created.conversation_id,
            session_token=raw_token,
            workspace_name=created.workspace_name,
            expires_at=created.expires_at,
        )

    async def get_conversation(
        self,
        conversation_id: UUID,
        token_hash: str,
    ) -> CustomerConversationResponse:
        try:
            return await self._gateway.get_conversation(conversation_id, token_hash)
        except CustomerChatGatewayError as error:
            raise _gateway_http_error(error) from error

    async def _fail_turn_safely(
        self,
        turn_id: UUID,
        token_hash: str,
        error_code: str,
    ) -> None:
        try:
            await self._gateway.fail_turn(turn_id, token_hash, error_code)
        except CustomerChatGatewayError:
            return

    async def submit_turn(
        self,
        conversation_id: UUID,
        token_hash: str,
        client_message_id: UUID,
        message: str,
    ) -> CustomerTurnResponse:
        if self._embedding_provider is None or self._generation_provider is None:
            raise CustomerChatHttpError(
                "Customer answer generation is not configured.",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
        try:
            normalized_message = normalize_question(message, minimum_chars=1)
        except RetrievalHttpError as error:
            raise CustomerChatHttpError(error.detail, error.status_code) from error

        try:
            started = await self._gateway.begin_turn(
                conversation_id,
                token_hash,
                client_message_id,
                normalized_message,
            )
        except CustomerChatGatewayError as error:
            raise _gateway_http_error(error) from error

        if started.conversation_id != conversation_id:
            raise CustomerChatHttpError("Customer chat returned an invalid conversation.")
        if started.turn_status == "completed":
            try:
                persisted = await self._gateway.get_turn_result(
                    conversation_id,
                    token_hash,
                    client_message_id,
                )
            except CustomerChatGatewayError as error:
                raise _gateway_http_error(error) from error
            return _turn_response(persisted, is_replay=True)
        if started.is_replay:
            raise CustomerChatHttpError(
                "This customer message is already being processed.",
                HTTPStatus.CONFLICT,
            )

        try:
            conversation = await self._gateway.get_conversation(
                conversation_id,
                token_hash,
            )
            if conversation.conversation_id != conversation_id or not conversation.messages:
                raise ValueError("Unexpected customer conversation state")
            current_message = conversation.messages[-1]
            if (
                current_message.role != "customer"
                or normalize_question(current_message.content, minimum_chars=1)
                != normalized_message
            ):
                raise ValueError("Unexpected current customer message")
            contextual_question = build_contextual_question(
                normalized_message,
                conversation.messages[:-1],
            )
        except (RetrievalHttpError, ValueError) as error:
            await self._fail_turn_safely(started.turn_id, token_hash, "retrieval_failed")
            raise CustomerChatHttpError(
                "The customer conversation could not be read safely.",
                HTTPStatus.BAD_GATEWAY,
            ) from error
        except CustomerChatGatewayError as error:
            await self._fail_turn_safely(
                started.turn_id,
                token_hash,
                "temporarily_unavailable",
            )
            raise _gateway_http_error(error) from error

        retrieval_gateway = self._gateway.retrieval_gateway(
            conversation_id,
            token_hash,
            started.workspace_id,
        )
        retrieval_service = KnowledgeRetrievalService(
            retrieval_gateway,
            self._embedding_provider,
            minimum_query_chars=1,
        )

        try:
            answer = await RagAnswerService(
                retrieval_service,
                self._generation_provider,
            ).answer(started.workspace_id, contextual_question)
            await self._gateway.complete_turn(
                started.turn_id,
                token_hash,
                answer.status,
                answer.answer,
                answer.citations,
            )
            persisted = await self._gateway.get_turn_result(
                conversation_id,
                token_hash,
                client_message_id,
            )
        except RetrievalHttpError as error:
            safe_code = (
                "temporarily_unavailable"
                if error.status_code == HTTPStatus.SERVICE_UNAVAILABLE
                else "retrieval_failed"
            )
            await self._fail_turn_safely(started.turn_id, token_hash, safe_code)
            raise CustomerChatHttpError(
                "The customer answer could not be retrieved safely.",
                error.status_code,
            ) from error
        except RagAnswerHttpError as error:
            safe_code = (
                "temporarily_unavailable"
                if error.status_code == HTTPStatus.SERVICE_UNAVAILABLE
                else "generation_failed"
            )
            await self._fail_turn_safely(started.turn_id, token_hash, safe_code)
            raise CustomerChatHttpError(
                "The grounded customer answer could not be generated safely.",
                error.status_code,
            ) from error
        except CustomerChatGatewayError as error:
            await self._fail_turn_safely(
                started.turn_id,
                token_hash,
                "temporarily_unavailable",
            )
            raise _gateway_http_error(error) from error
        except Exception as error:
            await self._fail_turn_safely(started.turn_id, token_hash, "generation_failed")
            raise CustomerChatHttpError(
                "The customer answer could not be completed safely.",
                HTTPStatus.BAD_GATEWAY,
            ) from error

        return _turn_response(persisted, is_replay=False)
