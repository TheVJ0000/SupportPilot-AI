import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from uuid import UUID

from app.ai.embeddings.base import EmbeddingProvider
from app.ai.generation.base import GenerationProvider
from app.ai.generation.errors import GenerationProviderError
from app.ai.generation.models import (
    MAX_GENERATED_ANSWER_CHARS,
    GenerationAnswerDelta,
    GenerationDecisionEvent,
    GenerationStreamComplete,
    canonicalize_evidence_ids,
)
from app.chat.context import build_contextual_question
from app.chat.errors import CustomerChatGatewayError, CustomerChatHttpError
from app.chat.gateway import CustomerChatGateway
from app.chat.models import (
    CustomerChatSessionResult,
    CustomerConversationResponse,
    CustomerFeedbackResponse,
    CustomerHumanRequestResponse,
    CustomerStreamComplete,
    CustomerStreamDelta,
    CustomerStreamError,
    CustomerStreamStarted,
    CustomerTurnResponse,
    CustomerTurnStreamEvent,
    PersistedCustomerTurn,
    PreparedCustomerTurnStream,
)
from app.chat.security import generate_customer_session_token, hash_customer_session_token
from app.rag.answering import (
    RagAnswerService,
    grounded_response_from_decision,
    insufficient_response,
    prepare_grounded_evidence,
)
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
        message_id=result.message_id,
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

    async def set_feedback(
        self,
        conversation_id: UUID,
        token_hash: str,
        message_id: UUID,
        rating: str,
    ) -> CustomerFeedbackResponse:
        try:
            return await self._gateway.set_feedback(
                conversation_id,
                token_hash,
                message_id,
                rating,
            )
        except CustomerChatGatewayError as error:
            raise _gateway_http_error(error) from error

    async def request_human_support(
        self,
        conversation_id: UUID,
        token_hash: str,
    ) -> CustomerHumanRequestResponse:
        try:
            return await self._gateway.request_human_support(conversation_id, token_hash)
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

    async def prepare_turn_stream(
        self,
        conversation_id: UUID,
        token_hash: str,
        client_message_id: UUID,
        message: str,
    ) -> PreparedCustomerTurnStream:
        """Begin idempotently and finish all safe preparation before SSE headers."""

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
            return PreparedCustomerTurnStream(
                started=started,
                client_message_id=client_message_id,
                question=normalized_message,
                grounded_evidence=None,
                replay_result=_turn_response(persisted, is_replay=True),
            )
        if started.is_replay:
            raise CustomerChatHttpError(
                "This customer message is already being processed.",
                HTTPStatus.CONFLICT,
            )

        try:
            conversation = await self._gateway.get_conversation(conversation_id, token_hash)
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

        retrieval_service = KnowledgeRetrievalService(
            self._gateway.retrieval_gateway(
                conversation_id,
                token_hash,
                started.workspace_id,
            ),
            self._embedding_provider,
            minimum_query_chars=1,
        )
        try:
            retrieval = await retrieval_service.retrieve(
                started.workspace_id,
                contextual_question,
            )
            grounded_evidence = prepare_grounded_evidence(retrieval)
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
            await self._fail_turn_safely(started.turn_id, token_hash, "retrieval_failed")
            raise CustomerChatHttpError(
                "The retrieved evidence could not be prepared safely.",
                error.status_code,
            ) from error
        except Exception as error:
            await self._fail_turn_safely(started.turn_id, token_hash, "retrieval_failed")
            raise CustomerChatHttpError(
                "The customer answer could not be retrieved safely.",
                HTTPStatus.BAD_GATEWAY,
            ) from error
        return PreparedCustomerTurnStream(
            started=started,
            client_message_id=client_message_id,
            question=contextual_question,
            grounded_evidence=grounded_evidence,
        )

    async def _fail_cancelled_turn(self, turn_id: UUID, token_hash: str) -> None:
        failure = asyncio.create_task(
            self._fail_turn_safely(turn_id, token_hash, "generation_failed")
        )
        try:
            await asyncio.shield(failure)
        except asyncio.CancelledError:
            return

    async def stream_prepared_turn(
        self,
        prepared: PreparedCustomerTurnStream,
        token_hash: str,
    ) -> AsyncIterator[CustomerTurnStreamEvent]:
        """Stream provisional text, then atomically persist and return the authority."""

        if prepared.replay_result is not None:
            yield CustomerStreamComplete(result=prepared.replay_result)
            return
        if self._generation_provider is None:
            await self._fail_turn_safely(
                prepared.started.turn_id,
                token_hash,
                "temporarily_unavailable",
            )
            yield CustomerStreamError()
            return

        started = prepared.started
        turn_committed = False
        try:
            yield CustomerStreamStarted(
                conversation_id=started.conversation_id,
                turn_id=started.turn_id,
                client_message_id=prepared.client_message_id,
            )
            if prepared.grounded_evidence is None:
                answer = insufficient_response(started.workspace_id, prepared.question)
            else:
                validated_prefix: GenerationDecisionEvent | None = None
                answer_parts: list[str] = []
                answer_length = 0
                final_result = None
                available_ids = [item.evidence_id for item in prepared.grounded_evidence.evidence]
                async for event in self._generation_provider.stream_grounded_answer(
                    prepared.question,
                    prepared.grounded_evidence.evidence,
                ):
                    if final_result is not None:
                        raise ValueError("Generation event arrived after completion")
                    if isinstance(event, GenerationDecisionEvent):
                        if validated_prefix is not None:
                            raise ValueError("Generation decision was emitted more than once")
                        canonical_ids = canonicalize_evidence_ids(event, available_ids)
                        validated_prefix = GenerationDecisionEvent(
                            decision=event.decision,
                            evidence_ids=canonical_ids,
                        )
                    elif isinstance(event, GenerationAnswerDelta):
                        if validated_prefix is None or validated_prefix.decision != "answerable":
                            raise ValueError("Unsafe answer delta ordering")
                        answer_parts.append(event.text)
                        answer_length += len(event.text)
                        if answer_length > MAX_GENERATED_ANSWER_CHARS:
                            raise ValueError("Generated answer exceeds the safe limit")
                        yield CustomerStreamDelta(text=event.text)
                    elif isinstance(event, GenerationStreamComplete):
                        if final_result is not None or validated_prefix is None:
                            raise ValueError("Invalid generation stream completion")
                        final_result = event.result
                    else:
                        raise ValueError("Unknown generation stream event")
                if final_result is None or validated_prefix is None:
                    raise ValueError("Generation stream ended before completion")
                final_prefix = GenerationDecisionEvent(
                    decision=final_result.decision,
                    evidence_ids=final_result.evidence_ids,
                )
                final_ids = canonicalize_evidence_ids(final_prefix, available_ids)
                if (
                    final_result.decision != validated_prefix.decision
                    or final_ids != validated_prefix.evidence_ids
                ):
                    raise ValueError("Final generation evidence did not match its prefix")
                answer = grounded_response_from_decision(
                    prepared.grounded_evidence,
                    final_result,
                )
                if answer.status == "answered" and answer.answer != "".join(answer_parts):
                    raise ValueError("Persisted answer would not match streamed text")
                if answer.status == "insufficient_evidence" and answer_parts:
                    raise ValueError("Insufficient answer exposed provisional model text")

            await self._gateway.complete_turn(
                started.turn_id,
                token_hash,
                answer.status,
                answer.answer,
                answer.citations,
            )
            persisted = await self._gateway.get_turn_result(
                started.conversation_id,
                token_hash,
                prepared.client_message_id,
            )
            response = _turn_response(persisted, is_replay=False)
            if (
                response.conversation_id != started.conversation_id
                or response.turn_id != started.turn_id
                or response.client_message_id != prepared.client_message_id
                or response.status != answer.status
                or response.answer != answer.answer
                or response.citations != answer.citations
            ):
                raise ValueError("Persisted turn result did not match the validated answer")
            turn_committed = True
            yield CustomerStreamComplete(result=response)
        except asyncio.CancelledError:
            if not turn_committed:
                await self._fail_cancelled_turn(started.turn_id, token_hash)
            raise
        except GeneratorExit:
            if not turn_committed:
                await self._fail_cancelled_turn(started.turn_id, token_hash)
            raise
        except GenerationProviderError as error:
            safe_code = (
                "temporarily_unavailable"
                if error.error_code
                in {
                    "generation_auth_failed",
                    "generation_rate_limited",
                    "generation_provider_unavailable",
                }
                else "generation_failed"
            )
            await self._fail_turn_safely(started.turn_id, token_hash, safe_code)
            yield CustomerStreamError()
        except (CustomerChatGatewayError, RagAnswerHttpError, ValueError, TypeError):
            await self._fail_turn_safely(started.turn_id, token_hash, "generation_failed")
            yield CustomerStreamError()
        except Exception:
            await self._fail_turn_safely(started.turn_id, token_hash, "generation_failed")
            yield CustomerStreamError()
