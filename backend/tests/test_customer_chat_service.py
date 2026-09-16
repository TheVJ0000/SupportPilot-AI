import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.ai.generation.errors import GenerationProviderError
from app.ai.generation.models import (
    GenerationAnswerDelta,
    GenerationDecisionEvent,
    GenerationStreamComplete,
    GroundedGenerationDecision,
)
from app.chat.errors import CustomerChatGatewayError, CustomerChatHttpError
from app.chat.models import (
    CreatedCustomerSession,
    CustomerConversationResponse,
    CustomerFeedbackResponse,
    CustomerHistoryMessage,
    CustomerHumanRequestResult,
    CustomerStreamComplete,
    CustomerStreamDelta,
    CustomerStreamError,
    CustomerStreamStarted,
    PersistedCustomerTurn,
    StartedCustomerTurn,
)
from app.chat.service import CustomerChatService
from app.knowledge.errors import GatewayError
from app.rag.answering import INSUFFICIENT_EVIDENCE_MESSAGE
from app.rag.models import RetrievedChunk, TrustedCitation

PUBLIC_ID = UUID("10000000-0000-4000-8000-000000000001")
WORKSPACE_ID = UUID("20000000-0000-4000-8000-000000000001")
SESSION_ID = UUID("30000000-0000-4000-8000-000000000001")
CONVERSATION_ID = UUID("40000000-0000-4000-8000-000000000001")
CLIENT_MESSAGE_ID = UUID("50000000-0000-4000-8000-000000000001")
TURN_ID = UUID("60000000-0000-4000-8000-000000000001")
MESSAGE_ID = UUID("90000000-0000-4000-8000-000000000010")
SOURCE_ID = UUID("70000000-0000-4000-8000-000000000001")
CHUNK_ID = UUID("80000000-0000-4000-8000-000000000001")
TOKEN_HASH = "a" * 64
NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)


class FakeRetrievalGateway:
    def __init__(self, matches=None, error: Exception | None = None) -> None:
        self.matches = [] if matches is None else matches
        self.error = error
        self.calls = 0

    async def search(self, workspace_id, query_embedding, *metadata):
        self.calls += 1
        assert workspace_id == WORKSPACE_ID
        assert len(query_embedding) == 768
        assert metadata == ("gemini", "gemini-embedding-2", 768, 8)
        if self.error:
            raise self.error
        return self.matches


class FakeEmbeddingProvider:
    provider_name = "gemini"
    model_name = "gemini-embedding-2"
    dimension = 768

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def embed_query(self, query: str) -> list[float]:
        self.calls.append(query)
        return [0.1] * 768


class FakeGenerationProvider:
    provider_name = "gemini"
    model_name = "gemini-3.8-flash"

    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result or GroundedGenerationDecision(
            decision="answerable",
            answer="Use the reset link.",
            evidence_ids=["E1"],
        )
        self.error = error
        self.calls = 0
        self.stream_calls = 0
        self.questions: list[str] = []

    async def generate_grounded_answer(self, question, evidence):
        self.calls += 1
        self.questions.append(question)
        assert question
        assert [item.evidence_id for item in evidence] == [
            f"E{index}" for index in range(1, len(evidence) + 1)
        ]
        if self.error:
            raise self.error
        return self.result

    async def stream_grounded_answer(self, question, evidence):
        self.stream_calls += 1
        self.questions.append(question)
        if self.error:
            raise self.error
        yield GenerationDecisionEvent(
            decision=self.result.decision,
            evidence_ids=self.result.evidence_ids,
        )
        if self.result.decision == "answerable":
            midpoint = max(1, len(self.result.answer) // 2)
            yield GenerationAnswerDelta(text=self.result.answer[:midpoint])
            if self.result.answer[midpoint:]:
                yield GenerationAnswerDelta(text=self.result.answer[midpoint:])
        yield GenerationStreamComplete(result=self.result)


class FakeCustomerChatGateway:
    def __init__(
        self,
        retrieval_gateway: FakeRetrievalGateway | None = None,
        started: StartedCustomerTurn | None = None,
        *,
        persist_current: bool = True,
    ) -> None:
        self.retrieval = retrieval_gateway or FakeRetrievalGateway()
        self.started = started or StartedCustomerTurn(
            turn_id=TURN_ID,
            workspace_id=WORKSPACE_ID,
            conversation_id=CONVERSATION_ID,
            turn_status="processing",
            is_replay=False,
        )
        self.create_calls = []
        self.begin_calls = []
        self.complete_calls = []
        self.fail_calls = []
        self.feedback_calls = []
        self.human_request_calls = []
        self.history_calls = 0
        self.persist_current = persist_current
        self.persisted: PersistedCustomerTurn | None = None
        self.history = CustomerConversationResponse(
            conversation_id=CONVERSATION_ID,
            status="open",
            messages=[],
        )

    async def create_session(self, public_id, token_hash, expires_at):
        self.create_calls.append((public_id, token_hash, expires_at))
        return CreatedCustomerSession(
            customer_session_id=SESSION_ID,
            conversation_id=CONVERSATION_ID,
            workspace_id=WORKSPACE_ID,
            workspace_name="Demo Workspace",
            expires_at=expires_at,
        )

    async def begin_turn(self, conversation_id, token_hash, client_message_id, message):
        self.begin_calls.append((conversation_id, token_hash, client_message_id, message))
        if self.persist_current and (
            not self.history.messages
            or self.history.messages[-1].role != "customer"
            or self.history.messages[-1].content != message
        ):
            self.history.messages.append(
                CustomerHistoryMessage(
                    id=UUID("90000000-0000-4000-8000-000000000001"),
                    role="customer",
                    content=message,
                    created_at=NOW,
                    citations=[],
                )
            )
        return self.started

    def retrieval_gateway(self, conversation_id, token_hash, workspace_id):
        assert (conversation_id, token_hash, workspace_id) == (
            CONVERSATION_ID,
            TOKEN_HASH,
            WORKSPACE_ID,
        )
        return self.retrieval

    async def complete_turn(self, turn_id, token_hash, answer_status, answer, citations):
        self.complete_calls.append((turn_id, token_hash, answer_status, answer, citations))
        self.persisted = PersistedCustomerTurn(
            turn_id=turn_id,
            conversation_id=CONVERSATION_ID,
            message_id=MESSAGE_ID,
            client_message_id=CLIENT_MESSAGE_ID,
            answer_status=answer_status,
            answer=answer,
            citations=citations,
        )

    async def fail_turn(self, turn_id, token_hash, error_code):
        self.fail_calls.append((turn_id, token_hash, error_code))

    async def get_turn_result(self, conversation_id, token_hash, client_message_id):
        assert (conversation_id, token_hash, client_message_id) == (
            CONVERSATION_ID,
            TOKEN_HASH,
            CLIENT_MESSAGE_ID,
        )
        if self.persisted is None:
            self.persisted = PersistedCustomerTurn(
                turn_id=TURN_ID,
                conversation_id=CONVERSATION_ID,
                message_id=MESSAGE_ID,
                client_message_id=CLIENT_MESSAGE_ID,
                answer_status="answered",
                answer="Persisted answer.",
                citations=[],
            )
        return self.persisted

    async def get_conversation(self, conversation_id, token_hash):
        assert (conversation_id, token_hash) == (CONVERSATION_ID, TOKEN_HASH)
        self.history_calls += 1
        return self.history

    async def set_feedback(self, conversation_id, token_hash, message_id, rating):
        self.feedback_calls.append((conversation_id, token_hash, message_id, rating))
        return CustomerFeedbackResponse(message_id=message_id, rating=rating)

    async def request_human_support(self, conversation_id, token_hash):
        self.human_request_calls.append((conversation_id, token_hash))
        return CustomerHumanRequestResult(
            conversation_id=conversation_id,
            status="human_requested",
            human_requested_at=NOW,
            escalation_id=UUID("a0000000-0000-4000-8000-000000000001"),
            triage_status="pending",
        )


def retrieved_chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=CHUNK_ID,
        source_id=SOURCE_ID,
        source_title="Trusted Account Help",
        source_type="file",
        chunk_index=2,
        content="Use the reset link.",
        locator={"kind": "pdf", "page_start": 3, "page_end": 3},
        similarity=0.87,
    )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_session_creation_returns_raw_token_once_but_passes_only_sha256() -> None:
    raw_token = "A" * 43
    gateway = FakeCustomerChatGateway()
    service = CustomerChatService(
        gateway,
        token_factory=lambda: raw_token,
        clock=lambda: NOW,
    )

    result = await service.create_session(PUBLIC_ID)

    public_id, token_hash, expires_at = gateway.create_calls[0]
    assert public_id == PUBLIC_ID
    assert token_hash == hashlib.sha256(raw_token.encode()).hexdigest()
    assert raw_token != token_hash
    assert expires_at == NOW + timedelta(days=7)
    assert result.session_token == raw_token
    assert raw_token not in repr(result)


@pytest.mark.anyio
async def test_grounded_turn_embeds_once_and_persists_only_trusted_citations() -> None:
    retrieval = FakeRetrievalGateway(matches=[retrieved_chunk()])
    gateway = FakeCustomerChatGateway(retrieval)
    embedding = FakeEmbeddingProvider()
    generation = FakeGenerationProvider()
    service = CustomerChatService(
        gateway,
        embedding_provider=embedding,
        generation_provider=generation,
    )

    result = await service.submit_turn(
        CONVERSATION_ID,
        TOKEN_HASH,
        CLIENT_MESSAGE_ID,
        "  How do I reset my password?  ",
    )

    assert gateway.begin_calls[0][3] == "How do I reset my password?"
    assert embedding.calls == ["How do I reset my password?"]
    assert retrieval.calls == 1
    assert generation.calls == 1
    assert result.status == "answered"
    assert result.is_replay is False
    persisted_citations = gateway.complete_calls[0][4]
    assert persisted_citations == [
        TrustedCitation(
            source_id=SOURCE_ID,
            source_title="Trusted Account Help",
            source_type="file",
            chunk_index=2,
            locator={"kind": "pdf", "page_start": 3, "page_end": 3},
        )
    ]


@pytest.mark.anyio
async def test_no_evidence_persists_standard_insufficient_answer_without_generation() -> None:
    gateway = FakeCustomerChatGateway(FakeRetrievalGateway(matches=[]))
    embedding = FakeEmbeddingProvider()
    generation = FakeGenerationProvider()

    result = await CustomerChatService(
        gateway,
        embedding_provider=embedding,
        generation_provider=generation,
    ).submit_turn(CONVERSATION_ID, TOKEN_HASH, CLIENT_MESSAGE_ID, "?")

    assert embedding.calls == ["?"]
    assert generation.calls == 0
    assert result.status == "insufficient_evidence"
    assert gateway.complete_calls[0][2:] == (
        "insufficient_evidence",
        INSUFFICIENT_EVIDENCE_MESSAGE,
        [],
    )


@pytest.mark.anyio
async def test_completed_retry_returns_persisted_result_without_ai_calls() -> None:
    started = StartedCustomerTurn(
        turn_id=TURN_ID,
        workspace_id=WORKSPACE_ID,
        conversation_id=CONVERSATION_ID,
        turn_status="completed",
        is_replay=True,
    )
    gateway = FakeCustomerChatGateway(started=started)
    embedding = FakeEmbeddingProvider()
    generation = FakeGenerationProvider()

    result = await CustomerChatService(
        gateway,
        embedding_provider=embedding,
        generation_provider=generation,
    ).submit_turn(CONVERSATION_ID, TOKEN_HASH, CLIENT_MESSAGE_ID, "Question?")

    assert result.is_replay is True
    assert result.answer == "Persisted answer."
    assert embedding.calls == []
    assert generation.calls == 0
    assert gateway.complete_calls == []
    assert gateway.history_calls == 0


@pytest.mark.anyio
async def test_processing_replay_returns_conflict_without_ai_calls() -> None:
    started = StartedCustomerTurn(
        turn_id=TURN_ID,
        workspace_id=WORKSPACE_ID,
        conversation_id=CONVERSATION_ID,
        turn_status="processing",
        is_replay=True,
    )
    gateway = FakeCustomerChatGateway(started=started)
    embedding = FakeEmbeddingProvider()

    with pytest.raises(CustomerChatHttpError) as caught:
        await CustomerChatService(
            gateway,
            embedding_provider=embedding,
            generation_provider=FakeGenerationProvider(),
        ).submit_turn(CONVERSATION_ID, TOKEN_HASH, CLIENT_MESSAGE_ID, "Question?")

    assert caught.value.status_code == 409
    assert embedding.calls == []


@pytest.mark.anyio
async def test_failed_turn_retry_reprocesses_the_existing_turn_once() -> None:
    retried = StartedCustomerTurn(
        turn_id=TURN_ID,
        workspace_id=WORKSPACE_ID,
        conversation_id=CONVERSATION_ID,
        turn_status="processing",
        is_replay=False,
    )
    retrieval = FakeRetrievalGateway(matches=[retrieved_chunk()])
    gateway = FakeCustomerChatGateway(retrieval, started=retried)
    gateway.history.messages = [
        CustomerHistoryMessage(
            id=UUID("90000000-0000-4000-8000-000000000002"),
            role="assistant",
            content="Earlier answer.",
            answer_status="answered",
            created_at=NOW,
            citations=[],
        ),
        CustomerHistoryMessage(
            id=UUID("90000000-0000-4000-8000-000000000001"),
            role="customer",
            content="Question?",
            created_at=NOW,
            citations=[],
        ),
    ]
    embedding = FakeEmbeddingProvider()
    generation = FakeGenerationProvider()

    result = await CustomerChatService(
        gateway,
        embedding_provider=embedding,
        generation_provider=generation,
    ).submit_turn(CONVERSATION_ID, TOKEN_HASH, CLIENT_MESSAGE_ID, "Question?")

    assert result.turn_id == TURN_ID
    assert len(gateway.begin_calls) == 1
    assert embedding.calls == [
        "Previous assistant: Earlier answer. Current customer question: Question?"
    ]
    assert generation.calls == 1
    assert generation.questions[0].count("Current customer question: Question?") == 1
    assert len(gateway.history.messages) == 2
    assert len(gateway.complete_calls) == 1
    assert gateway.fail_calls == []


@pytest.mark.anyio
async def test_generation_failure_marks_turn_failed_with_only_safe_code() -> None:
    gateway = FakeCustomerChatGateway(FakeRetrievalGateway(matches=[retrieved_chunk()]))
    generation = FakeGenerationProvider(
        error=GenerationProviderError("generation_provider_unavailable")
    )

    with pytest.raises(CustomerChatHttpError) as caught:
        await CustomerChatService(
            gateway,
            embedding_provider=FakeEmbeddingProvider(),
            generation_provider=generation,
        ).submit_turn(CONVERSATION_ID, TOKEN_HASH, CLIENT_MESSAGE_ID, "Question?")

    assert caught.value.status_code == 503
    assert gateway.fail_calls == [(TURN_ID, TOKEN_HASH, "temporarily_unavailable")]
    assert "provider" not in gateway.fail_calls[0][2]


@pytest.mark.anyio
async def test_retrieval_failure_marks_turn_failed_without_provider_detail() -> None:
    retrieval = FakeRetrievalGateway(
        error=GatewayError("search_customer_chat_knowledge", "private provider body")
    )
    gateway = FakeCustomerChatGateway(retrieval)

    with pytest.raises(CustomerChatHttpError) as caught:
        await CustomerChatService(
            gateway,
            embedding_provider=FakeEmbeddingProvider(),
            generation_provider=FakeGenerationProvider(),
        ).submit_turn(CONVERSATION_ID, TOKEN_HASH, CLIENT_MESSAGE_ID, "Question?")

    assert caught.value.status_code == 502
    assert gateway.fail_calls == [(TURN_ID, TOKEN_HASH, "retrieval_failed")]
    assert "private" not in caught.value.detail


@pytest.mark.anyio
async def test_invalid_or_expired_session_error_is_safe() -> None:
    class RejectedGateway(FakeCustomerChatGateway):
        async def begin_turn(self, *args):
            raise CustomerChatGatewayError("begin_customer_chat_turn", "28000")

    with pytest.raises(CustomerChatHttpError) as caught:
        await CustomerChatService(
            RejectedGateway(),
            embedding_provider=FakeEmbeddingProvider(),
            generation_provider=FakeGenerationProvider(),
        ).submit_turn(CONVERSATION_ID, TOKEN_HASH, CLIENT_MESSAGE_ID, "Question?")

    assert caught.value.status_code == 401
    assert "hash" not in caught.value.detail


@pytest.mark.anyio
async def test_history_is_returned_in_gateway_order_without_session_metadata() -> None:
    gateway = FakeCustomerChatGateway()
    gateway.history.messages = [
        CustomerHistoryMessage(
            id=UUID("90000000-0000-4000-8000-000000000001"),
            role="customer",
            content="Question?",
            created_at=NOW,
            citations=[],
        )
    ]

    history = await CustomerChatService(gateway).get_conversation(CONVERSATION_ID, TOKEN_HASH)

    assert history.messages[0].role == "customer"
    serialized = history.model_dump_json()
    assert "token" not in serialized
    assert "embedding" not in serialized


@pytest.mark.anyio
async def test_feedback_and_human_request_delegate_only_to_narrow_gateway_methods() -> None:
    gateway = FakeCustomerChatGateway()
    service = CustomerChatService(gateway)

    feedback = await service.set_feedback(
        CONVERSATION_ID,
        TOKEN_HASH,
        MESSAGE_ID,
        "positive",
    )
    human_request = await service.request_human_support(CONVERSATION_ID, TOKEN_HASH)

    assert feedback.rating == "positive"
    assert gateway.feedback_calls == [(CONVERSATION_ID, TOKEN_HASH, MESSAGE_ID, "positive")]
    assert human_request.status == "human_requested"
    assert gateway.human_request_calls == [(CONVERSATION_ID, TOKEN_HASH)]


@pytest.mark.anyio
async def test_new_turn_uses_trusted_history_once_but_persists_original_question() -> None:
    retrieval = FakeRetrievalGateway(matches=[retrieved_chunk()])
    gateway = FakeCustomerChatGateway(retrieval)
    gateway.history.messages = [
        CustomerHistoryMessage(
            id=UUID("90000000-0000-4000-8000-000000000002"),
            role="customer",
            content="What is your refund policy?",
            created_at=NOW,
            citations=[],
        ),
        CustomerHistoryMessage(
            id=UUID("90000000-0000-4000-8000-000000000003"),
            role="assistant",
            content="Refunds are available within 30 days.",
            answer_status="answered",
            created_at=NOW,
            citations=[],
        ),
    ]
    embedding = FakeEmbeddingProvider()
    generation = FakeGenerationProvider()

    await CustomerChatService(
        gateway,
        embedding_provider=embedding,
        generation_provider=generation,
    ).submit_turn(
        CONVERSATION_ID,
        TOKEN_HASH,
        CLIENT_MESSAGE_ID,
        "  What about after that?  ",
    )

    contextual = (
        "Previous customer: What is your refund policy? "
        "Previous assistant: Refunds are available within 30 days. "
        "Current customer question: What about after that?"
    )
    assert gateway.history_calls == 1
    assert gateway.begin_calls[0][3] == "What about after that?"
    assert gateway.history.messages[-1].content == "What about after that?"
    assert embedding.calls == [contextual]
    assert retrieval.calls == 1
    assert generation.questions == [contextual]
    assert all(call[3] != contextual for call in gateway.begin_calls)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("final_role", "final_content"),
    [
        ("assistant", "Not the current customer message."),
        ("customer", "A different customer question."),
    ],
)
async def test_unexpected_final_history_message_fails_before_ai(
    final_role: str,
    final_content: str,
) -> None:
    gateway = FakeCustomerChatGateway(
        FakeRetrievalGateway(matches=[retrieved_chunk()]),
        persist_current=False,
    )
    gateway.history.messages = [
        CustomerHistoryMessage(
            id=UUID("90000000-0000-4000-8000-000000000002"),
            role=final_role,
            content=final_content,
            answer_status="answered" if final_role == "assistant" else None,
            created_at=NOW,
            citations=[],
        )
    ]
    embedding = FakeEmbeddingProvider()
    generation = FakeGenerationProvider()

    with pytest.raises(CustomerChatHttpError) as caught:
        await CustomerChatService(
            gateway,
            embedding_provider=embedding,
            generation_provider=generation,
        ).submit_turn(CONVERSATION_ID, TOKEN_HASH, CLIENT_MESSAGE_ID, "Question?")

    assert caught.value.status_code == 502
    assert gateway.fail_calls == [(TURN_ID, TOKEN_HASH, "retrieval_failed")]
    assert embedding.calls == []
    assert generation.calls == 0


@pytest.mark.anyio
async def test_grounded_stream_persists_only_after_deltas_and_returns_authority() -> None:
    retrieval = FakeRetrievalGateway(matches=[retrieved_chunk()])
    gateway = FakeCustomerChatGateway(retrieval)
    embedding = FakeEmbeddingProvider()
    generation = FakeGenerationProvider()
    service = CustomerChatService(
        gateway,
        embedding_provider=embedding,
        generation_provider=generation,
    )

    prepared = await service.prepare_turn_stream(
        CONVERSATION_ID,
        TOKEN_HASH,
        CLIENT_MESSAGE_ID,
        "How do I reset?",
    )
    events = [event async for event in service.stream_prepared_turn(prepared, TOKEN_HASH)]

    assert isinstance(events[0], CustomerStreamStarted)
    assert isinstance(events[-1], CustomerStreamComplete)
    deltas = [event.text for event in events if isinstance(event, CustomerStreamDelta)]
    assert "".join(deltas) == "Use the reset link."
    assert gateway.begin_calls == [
        (CONVERSATION_ID, TOKEN_HASH, CLIENT_MESSAGE_ID, "How do I reset?")
    ]
    assert len(embedding.calls) == 1
    assert retrieval.calls == 1
    assert generation.stream_calls == 1
    assert len(gateway.complete_calls) == 1
    assert gateway.complete_calls[0][3] == "".join(deltas)
    assert gateway.complete_calls[0][4] == [
        TrustedCitation(
            source_id=SOURCE_ID,
            source_title="Trusted Account Help",
            source_type="file",
            chunk_index=2,
            locator={"kind": "pdf", "page_start": 3, "page_end": 3},
        )
    ]


@pytest.mark.anyio
async def test_stream_no_evidence_skips_generation_and_persists_deterministic_answer() -> None:
    gateway = FakeCustomerChatGateway(FakeRetrievalGateway())
    embedding = FakeEmbeddingProvider()
    generation = FakeGenerationProvider()
    service = CustomerChatService(
        gateway,
        embedding_provider=embedding,
        generation_provider=generation,
    )

    prepared = await service.prepare_turn_stream(
        CONVERSATION_ID, TOKEN_HASH, CLIENT_MESSAGE_ID, "Unknown?"
    )
    events = [event async for event in service.stream_prepared_turn(prepared, TOKEN_HASH)]

    assert generation.stream_calls == 0
    assert not any(isinstance(event, CustomerStreamDelta) for event in events)
    assert gateway.complete_calls[0][2:] == (
        "insufficient_evidence",
        INSUFFICIENT_EVIDENCE_MESSAGE,
        [],
    )
    assert isinstance(events[-1], CustomerStreamComplete)


@pytest.mark.anyio
async def test_model_insufficient_stream_exposes_no_model_answer_delta() -> None:
    result = GroundedGenerationDecision(
        decision="insufficient_evidence",
        evidence_ids=[],
        answer="",
    )
    gateway = FakeCustomerChatGateway(FakeRetrievalGateway(matches=[retrieved_chunk()]))
    generation = FakeGenerationProvider(result=result)
    service = CustomerChatService(
        gateway,
        embedding_provider=FakeEmbeddingProvider(),
        generation_provider=generation,
    )

    prepared = await service.prepare_turn_stream(
        CONVERSATION_ID, TOKEN_HASH, CLIENT_MESSAGE_ID, "Unsupported?"
    )
    events = [event async for event in service.stream_prepared_turn(prepared, TOKEN_HASH)]

    assert not any(isinstance(event, CustomerStreamDelta) for event in events)
    assert gateway.complete_calls[0][2:] == (
        "insufficient_evidence",
        INSUFFICIENT_EVIDENCE_MESSAGE,
        [],
    )


@pytest.mark.anyio
async def test_invalid_stream_evidence_emits_no_delta_and_fails_turn() -> None:
    invalid = GroundedGenerationDecision(
        decision="answerable",
        evidence_ids=["E9"],
        answer="Untrusted answer.",
    )
    gateway = FakeCustomerChatGateway(FakeRetrievalGateway(matches=[retrieved_chunk()]))
    service = CustomerChatService(
        gateway,
        embedding_provider=FakeEmbeddingProvider(),
        generation_provider=FakeGenerationProvider(result=invalid),
    )

    prepared = await service.prepare_turn_stream(
        CONVERSATION_ID, TOKEN_HASH, CLIENT_MESSAGE_ID, "Question?"
    )
    events = [event async for event in service.stream_prepared_turn(prepared, TOKEN_HASH)]

    assert not any(isinstance(event, CustomerStreamDelta) for event in events)
    assert isinstance(events[-1], CustomerStreamError)
    assert gateway.complete_calls == []
    assert gateway.fail_calls == [(TURN_ID, TOKEN_HASH, "generation_failed")]


@pytest.mark.anyio
async def test_completed_stream_replay_skips_all_ai_and_emits_only_complete() -> None:
    started = StartedCustomerTurn(
        turn_id=TURN_ID,
        workspace_id=WORKSPACE_ID,
        conversation_id=CONVERSATION_ID,
        turn_status="completed",
        is_replay=True,
    )
    gateway = FakeCustomerChatGateway(started=started)
    embedding = FakeEmbeddingProvider()
    generation = FakeGenerationProvider()
    service = CustomerChatService(
        gateway,
        embedding_provider=embedding,
        generation_provider=generation,
    )

    prepared = await service.prepare_turn_stream(
        CONVERSATION_ID, TOKEN_HASH, CLIENT_MESSAGE_ID, "Question?"
    )
    events = [event async for event in service.stream_prepared_turn(prepared, TOKEN_HASH)]

    assert len(events) == 1
    assert isinstance(events[0], CustomerStreamComplete)
    assert events[0].result.is_replay is True
    assert embedding.calls == []
    assert gateway.retrieval.calls == 0
    assert generation.stream_calls == 0


@pytest.mark.anyio
async def test_stream_cancellation_marks_turn_failed_without_persisting_assistant() -> None:
    blocker = asyncio.Event()

    class BlockingGenerationProvider(FakeGenerationProvider):
        async def stream_grounded_answer(self, question, evidence):
            self.stream_calls += 1
            yield GenerationDecisionEvent(decision="answerable", evidence_ids=["E1"])
            await blocker.wait()
            yield GenerationAnswerDelta(text="Never reached")

    gateway = FakeCustomerChatGateway(FakeRetrievalGateway(matches=[retrieved_chunk()]))
    service = CustomerChatService(
        gateway,
        embedding_provider=FakeEmbeddingProvider(),
        generation_provider=BlockingGenerationProvider(),
    )
    prepared = await service.prepare_turn_stream(
        CONVERSATION_ID, TOKEN_HASH, CLIENT_MESSAGE_ID, "Question?"
    )
    stream = service.stream_prepared_turn(prepared, TOKEN_HASH)
    assert isinstance(await anext(stream), CustomerStreamStarted)
    pending = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    pending.cancel()

    with pytest.raises(asyncio.CancelledError):
        await pending

    assert gateway.complete_calls == []
    assert gateway.fail_calls == [(TURN_ID, TOKEN_HASH, "generation_failed")]


@pytest.mark.anyio
async def test_failed_stream_retry_reuses_turn_and_customer_message_then_completes() -> None:
    gateway = FakeCustomerChatGateway(FakeRetrievalGateway(matches=[retrieved_chunk()]))
    generation = FakeGenerationProvider(error=GenerationProviderError("generation_failed"))
    service = CustomerChatService(
        gateway,
        embedding_provider=FakeEmbeddingProvider(),
        generation_provider=generation,
    )

    first = await service.prepare_turn_stream(
        CONVERSATION_ID, TOKEN_HASH, CLIENT_MESSAGE_ID, "Retry safely"
    )
    first_events = [event async for event in service.stream_prepared_turn(first, TOKEN_HASH)]
    generation.error = None
    retry = await service.prepare_turn_stream(
        CONVERSATION_ID, TOKEN_HASH, CLIENT_MESSAGE_ID, "Retry safely"
    )
    retry_events = [event async for event in service.stream_prepared_turn(retry, TOKEN_HASH)]

    assert isinstance(first_events[-1], CustomerStreamError)
    assert isinstance(retry_events[-1], CustomerStreamComplete)
    assert len(gateway.begin_calls) == 2
    assert len([message for message in gateway.history.messages if message.role == "customer"]) == 1
    assert generation.stream_calls == 2
    assert len(gateway.complete_calls) == 1
