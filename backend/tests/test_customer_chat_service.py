import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.ai.generation.errors import GenerationProviderError
from app.ai.generation.models import GroundedGenerationDecision
from app.chat.errors import CustomerChatGatewayError, CustomerChatHttpError
from app.chat.models import (
    CreatedCustomerSession,
    CustomerConversationResponse,
    CustomerHistoryMessage,
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

    async def generate_grounded_answer(self, question, evidence):
        self.calls += 1
        assert question
        assert [item.evidence_id for item in evidence] == [
            f"E{index}" for index in range(1, len(evidence) + 1)
        ]
        if self.error:
            raise self.error
        return self.result


class FakeCustomerChatGateway:
    def __init__(
        self,
        retrieval_gateway: FakeRetrievalGateway | None = None,
        started: StartedCustomerTurn | None = None,
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
        self.persisted: PersistedCustomerTurn | None = None
        self.history = CustomerConversationResponse(
            conversation_id=CONVERSATION_ID,
            status="open",
            messages=[
                CustomerHistoryMessage(
                    id=UUID("90000000-0000-4000-8000-000000000001"),
                    role="customer",
                    content="Question?",
                    created_at=NOW,
                    citations=[],
                )
            ],
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
                client_message_id=CLIENT_MESSAGE_ID,
                answer_status="answered",
                answer="Persisted answer.",
                citations=[],
            )
        return self.persisted

    async def get_conversation(self, conversation_id, token_hash):
        assert (conversation_id, token_hash) == (CONVERSATION_ID, TOKEN_HASH)
        return self.history


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
    embedding = FakeEmbeddingProvider()
    generation = FakeGenerationProvider()

    result = await CustomerChatService(
        gateway,
        embedding_provider=embedding,
        generation_provider=generation,
    ).submit_turn(CONVERSATION_ID, TOKEN_HASH, CLIENT_MESSAGE_ID, "Question?")

    assert result.turn_id == TURN_ID
    assert len(gateway.begin_calls) == 1
    assert embedding.calls == ["Question?"]
    assert generation.calls == 1
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

    history = await CustomerChatService(gateway).get_conversation(CONVERSATION_ID, TOKEN_HASH)

    assert history.messages[0].role == "customer"
    serialized = history.model_dump_json()
    assert "token" not in serialized
    assert "embedding" not in serialized
