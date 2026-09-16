import json
from datetime import UTC, datetime
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from app.ai.embeddings.factory import get_embedding_provider
from app.ai.generation.factory import get_generation_provider
from app.ai.generation.models import (
    GenerationAnswerDelta,
    GenerationDecisionEvent,
    GenerationStreamComplete,
    GroundedGenerationDecision,
)
from app.chat.errors import CustomerChatGatewayError
from app.chat.gateway import get_customer_chat_gateway
from app.chat.models import (
    CreatedCustomerSession,
    CustomerConversationResponse,
    CustomerFeedbackResponse,
    CustomerHistoryMessage,
    CustomerHumanRequestResult,
    PersistedCustomerTurn,
    StartedCustomerTurn,
)
from app.chat.security import hash_customer_session_token
from app.core.config import Settings, get_settings
from app.escalations.background import get_background_triage_runner
from app.escalations.service import EscalationTriageService
from app.main import app
from app.rag.models import RetrievedChunk

PUBLIC_ID = UUID("10000000-0000-4000-8000-000000000001")
WORKSPACE_ID = UUID("20000000-0000-4000-8000-000000000001")
SESSION_ID = UUID("30000000-0000-4000-8000-000000000001")
CONVERSATION_ID = UUID("40000000-0000-4000-8000-000000000001")
CLIENT_MESSAGE_ID = UUID("50000000-0000-4000-8000-000000000001")
TURN_ID = UUID("60000000-0000-4000-8000-000000000001")
SOURCE_ID = UUID("70000000-0000-4000-8000-000000000001")
CHUNK_ID = UUID("80000000-0000-4000-8000-000000000001")
MESSAGE_ID = UUID("90000000-0000-4000-8000-000000000001")
ASSISTANT_MESSAGE_ID = UUID("90000000-0000-4000-8000-000000000002")
ESCALATION_ID = UUID("a0000000-0000-4000-8000-000000000001")
CUSTOMER_TOKEN = "A" * 43
TOKEN_HASH = hash_customer_session_token(CUSTOMER_TOKEN)
NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)


class ApiEmbeddingProvider:
    provider_name = "gemini"
    model_name = "gemini-embedding-2"
    dimension = 768

    def __init__(self) -> None:
        self.calls = 0

    async def embed_query(self, query: str) -> list[float]:
        self.calls += 1
        assert query
        return [0.1] * 768


class ApiGenerationProvider:
    provider_name = "gemini"
    model_name = "gemini-3.8-flash"

    def __init__(self) -> None:
        self.calls = 0
        self.stream_calls = 0

    async def generate_grounded_answer(self, question, evidence):
        self.calls += 1
        assert question == "How do I reset my password?"
        assert [item.evidence_id for item in evidence] == ["E1"]
        return GroundedGenerationDecision(
            decision="answerable",
            answer="Use the reset link.",
            evidence_ids=["E1"],
        )

    async def stream_grounded_answer(self, question, evidence):
        self.stream_calls += 1
        assert question == "How do I reset my password?"
        assert [item.evidence_id for item in evidence] == ["E1"]
        result = GroundedGenerationDecision(
            decision="answerable",
            evidence_ids=["E1"],
            answer="Use the reset link.",
        )
        yield GenerationDecisionEvent(decision="answerable", evidence_ids=["E1"])
        yield GenerationAnswerDelta(text="Use the ")
        yield GenerationAnswerDelta(text="reset link.")
        yield GenerationStreamComplete(result=result)


class ApiRetrievalGateway:
    def __init__(self, with_evidence: bool) -> None:
        self.with_evidence = with_evidence

    async def search(self, *args):
        if not self.with_evidence:
            return []
        return [
            RetrievedChunk(
                chunk_id=CHUNK_ID,
                source_id=SOURCE_ID,
                source_title="Account Help",
                source_type="file",
                chunk_index=2,
                content="Use the reset link.",
                locator={"kind": "pdf", "page_start": 3, "page_end": 3},
                similarity=0.87,
            )
        ]


class ApiCustomerChatGateway:
    def __init__(self, *, with_evidence: bool = True) -> None:
        self.with_evidence = with_evidence
        self.created_hash: str | None = None
        self.completed: PersistedCustomerTurn | None = None
        self.feedback_calls: list[tuple] = []
        self.feedback_by_message: dict[UUID, str] = {}
        self.human_request_calls = 0
        self.background_triage_calls = []
        self.status = "open"
        self.human_requested_at = None

    async def create_session(self, public_id, token_hash, expires_at):
        assert public_id == PUBLIC_ID
        self.created_hash = token_hash
        return CreatedCustomerSession(
            customer_session_id=SESSION_ID,
            conversation_id=CONVERSATION_ID,
            workspace_id=WORKSPACE_ID,
            workspace_name="Demo Workspace",
            expires_at=expires_at,
        )

    async def begin_turn(self, conversation_id, token_hash, client_message_id, message):
        if token_hash != TOKEN_HASH:
            raise CustomerChatGatewayError("begin_customer_chat_turn", "28000")
        assert conversation_id == CONVERSATION_ID
        assert client_message_id == CLIENT_MESSAGE_ID
        assert message == "How do I reset my password?"
        if self.status != "open":
            raise CustomerChatGatewayError("begin_customer_chat_turn", "55000")
        return StartedCustomerTurn(
            turn_id=TURN_ID,
            workspace_id=WORKSPACE_ID,
            conversation_id=CONVERSATION_ID,
            turn_status="processing",
            is_replay=False,
        )

    def retrieval_gateway(self, conversation_id, token_hash, workspace_id):
        assert (conversation_id, token_hash, workspace_id) == (
            CONVERSATION_ID,
            TOKEN_HASH,
            WORKSPACE_ID,
        )
        return ApiRetrievalGateway(self.with_evidence)

    async def complete_turn(self, turn_id, token_hash, answer_status, answer, citations):
        self.completed = PersistedCustomerTurn(
            turn_id=turn_id,
            conversation_id=CONVERSATION_ID,
            message_id=ASSISTANT_MESSAGE_ID,
            client_message_id=CLIENT_MESSAGE_ID,
            answer_status=answer_status,
            answer=answer,
            citations=citations,
        )

    async def get_turn_result(self, conversation_id, token_hash, client_message_id):
        assert self.completed is not None
        return self.completed

    async def fail_turn(self, *args):
        raise AssertionError("Successful API test should not fail its turn")

    async def get_conversation(self, conversation_id, token_hash):
        if token_hash != TOKEN_HASH:
            raise CustomerChatGatewayError("get_customer_conversation", "28000")
        return CustomerConversationResponse(
            conversation_id=conversation_id,
            status=self.status,
            human_requested_at=self.human_requested_at,
            messages=[
                CustomerHistoryMessage(
                    id=MESSAGE_ID,
                    role="customer",
                    content="How do I reset my password?",
                    created_at=NOW,
                    citations=[],
                )
            ],
        )

    async def set_feedback(self, conversation_id, token_hash, message_id, rating):
        if token_hash != TOKEN_HASH:
            raise CustomerChatGatewayError("set_customer_message_feedback", "28000")
        if message_id != ASSISTANT_MESSAGE_ID:
            raise CustomerChatGatewayError("set_customer_message_feedback", "55000")
        self.feedback_calls.append((conversation_id, token_hash, message_id, rating))
        self.feedback_by_message[message_id] = rating
        return CustomerFeedbackResponse(message_id=message_id, rating=rating)

    async def request_human_support(self, conversation_id, token_hash):
        if token_hash != TOKEN_HASH:
            raise CustomerChatGatewayError("request_customer_human_support", "28000")
        self.human_request_calls += 1
        self.status = "human_requested"
        self.human_requested_at = NOW
        return CustomerHumanRequestResult(
            conversation_id=conversation_id,
            status="human_requested",
            human_requested_at=self.human_requested_at,
            escalation_id=ESCALATION_ID,
            triage_status="pending",
        )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    yield
    app.dependency_overrides.clear()


def configure_dependencies(gateway: ApiCustomerChatGateway):
    embedding = ApiEmbeddingProvider()
    generation = ApiGenerationProvider()
    app.dependency_overrides[get_customer_chat_gateway] = lambda: gateway
    app.dependency_overrides[get_embedding_provider] = lambda: embedding
    app.dependency_overrides[get_generation_provider] = lambda: generation

    async def run_triage(escalation_id):
        assert gateway.status == "human_requested"
        gateway.background_triage_calls.append(escalation_id)

    app.dependency_overrides[get_background_triage_runner] = lambda: run_triage
    return embedding, generation


@pytest.mark.anyio
async def test_public_session_endpoint_needs_no_supabase_jwt_and_returns_raw_token_once() -> None:
    gateway = ApiCustomerChatGateway()
    app.dependency_overrides[get_customer_chat_gateway] = lambda: gateway

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/chat/{PUBLIC_ID}/session")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"conversation_id", "session_token", "workspace_name", "expires_at"}
    assert body["conversation_id"] == str(CONVERSATION_ID)
    assert body["workspace_name"] == "Demo Workspace"
    assert gateway.created_hash == hash_customer_session_token(body["session_token"])
    assert body["session_token"] != gateway.created_hash
    assert "workspace_id" not in body
    assert "token_hash" not in body


@pytest.mark.anyio
async def test_unknown_public_chat_id_is_rejected_without_detail() -> None:
    class UnknownChatGateway(ApiCustomerChatGateway):
        async def create_session(self, *args):
            raise CustomerChatGatewayError("create_customer_chat_session", "22023")

    app.dependency_overrides[get_customer_chat_gateway] = UnknownChatGateway
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/chat/{PUBLIC_ID}/session")

    assert response.status_code == 404
    assert response.json() == {"detail": "Customer chat is unavailable."}


@pytest.mark.anyio
async def test_missing_secret_configuration_affects_only_customer_chat() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        supabase_url="https://project.example.test",
        supabase_secret_key=None,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        chat = await client.post(f"/api/chat/{PUBLIC_ID}/session")
        health = await client.get("/api/health")

    assert chat.status_code == 503
    assert chat.json() == {"detail": "Customer chat is not configured yet."}
    assert health.status_code == 200


@pytest.mark.anyio
async def test_turn_requires_well_formed_customer_session_header() -> None:
    configure_dependencies(ApiCustomerChatGateway())
    path = f"/api/chat/conversations/{CONVERSATION_ID}/turns"
    payload = {"client_message_id": str(CLIENT_MESSAGE_ID), "message": "Question?"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.post(path, json=payload)
        malformed = await client.post(
            path,
            headers={"X-SupportPilot-Session": "not valid"},
            json=payload,
        )

    assert missing.status_code == 401
    assert malformed.status_code == 401
    assert CUSTOMER_TOKEN not in missing.text + malformed.text


@pytest.mark.anyio
async def test_turn_rejects_invalid_input_and_client_selected_rag_configuration() -> None:
    configure_dependencies(ApiCustomerChatGateway())
    path = f"/api/chat/conversations/{CONVERSATION_ID}/turns"
    headers = {"X-SupportPilot-Session": CUSTOMER_TOKEN}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        invalid_id = await client.post(
            path,
            headers=headers,
            json={"client_message_id": "not-a-uuid", "message": "Question?"},
        )
        empty = await client.post(
            path,
            headers=headers,
            json={"client_message_id": str(CLIENT_MESSAGE_ID), "message": " "},
        )
        too_long = await client.post(
            path,
            headers=headers,
            json={"client_message_id": str(CLIENT_MESSAGE_ID), "message": "x" * 2001},
        )
        client_config = await client.post(
            path,
            headers=headers,
            json={
                "client_message_id": str(CLIENT_MESSAGE_ID),
                "message": "Question?",
                "workspace_id": str(WORKSPACE_ID),
                "provider": "attacker",
                "model": "attacker",
                "query_embedding": [0.1],
                "system_prompt": "attacker",
                "match_count": 100,
            },
        )

    assert invalid_id.status_code == 422
    assert empty.status_code == 422
    assert too_long.status_code == 422
    assert client_config.status_code == 422


@pytest.mark.anyio
async def test_turn_returns_persisted_grounded_answer_without_secrets_or_vectors() -> None:
    gateway = ApiCustomerChatGateway(with_evidence=True)
    embedding, generation = configure_dependencies(gateway)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/chat/conversations/{CONVERSATION_ID}/turns",
            headers={"X-SupportPilot-Session": CUSTOMER_TOKEN},
            json={
                "client_message_id": str(CLIENT_MESSAGE_ID),
                "message": "How do I reset my password?",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "answered"
    assert body["message_id"] == str(ASSISTANT_MESSAGE_ID)
    assert body["answer"] == "Use the reset link."
    assert body["citations"][0]["source_id"] == str(SOURCE_ID)
    assert body["citations"][0]["source_title"] == "Account Help"
    assert embedding.calls == 1
    assert generation.calls == 1
    for forbidden in (CUSTOMER_TOKEN, TOKEN_HASH, "embedding", "similarity", "secret"):
        assert forbidden not in response.text


@pytest.mark.anyio
async def test_history_returns_ordered_safe_messages_with_no_session_metadata() -> None:
    gateway = ApiCustomerChatGateway()
    app.dependency_overrides[get_customer_chat_gateway] = lambda: gateway
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/api/chat/conversations/{CONVERSATION_ID}",
            headers={"X-SupportPilot-Session": CUSTOMER_TOKEN},
        )

    assert response.status_code == 200
    assert response.json() == {
        "conversation_id": str(CONVERSATION_ID),
        "status": "open",
        "messages": [
            {
                "id": str(MESSAGE_ID),
                "role": "customer",
                "content": "How do I reset my password?",
                "created_at": NOW.isoformat().replace("+00:00", "Z"),
                "citations": [],
            }
        ],
    }
    assert "token" not in response.text
    assert "workspace" not in response.text


@pytest.mark.anyio
async def test_history_restores_assistant_feedback_and_human_request_state() -> None:
    class RestoredGateway(ApiCustomerChatGateway):
        async def get_conversation(self, conversation_id, token_hash):
            return CustomerConversationResponse(
                conversation_id=conversation_id,
                status="human_requested",
                human_requested_at=NOW,
                messages=[
                    CustomerHistoryMessage(
                        id=ASSISTANT_MESSAGE_ID,
                        role="assistant",
                        content="A grounded answer.",
                        answer_status="answered",
                        created_at=NOW,
                        citations=[],
                        feedback="negative",
                    )
                ],
            )

    app.dependency_overrides[get_customer_chat_gateway] = RestoredGateway
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/api/chat/conversations/{CONVERSATION_ID}",
            headers={"X-SupportPilot-Session": CUSTOMER_TOKEN},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "human_requested"
    assert response.json()["human_requested_at"] == NOW.isoformat().replace("+00:00", "Z")
    assert response.json()["messages"][0]["feedback"] == "negative"


@pytest.mark.anyio
async def test_wrong_session_token_is_rejected_safely() -> None:
    configure_dependencies(ApiCustomerChatGateway())
    wrong_token = "B" * 43
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/chat/conversations/{CONVERSATION_ID}/turns",
            headers={"X-SupportPilot-Session": wrong_token},
            json={
                "client_message_id": str(CLIENT_MESSAGE_ID),
                "message": "How do I reset my password?",
            },
        )

    assert response.status_code == 401
    assert wrong_token not in response.text


@pytest.mark.anyio
async def test_feedback_requires_session_and_strict_rating_body() -> None:
    gateway = ApiCustomerChatGateway()
    configure_dependencies(gateway)
    path = f"/api/chat/conversations/{CONVERSATION_ID}/messages/{ASSISTANT_MESSAGE_ID}/feedback"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.put(path, json={"rating": "positive"})
        invalid = await client.put(
            path,
            headers={"X-SupportPilot-Session": CUSTOMER_TOKEN},
            json={"rating": "neutral"},
        )
        extra = await client.put(
            path,
            headers={"X-SupportPilot-Session": CUSTOMER_TOKEN},
            json={"rating": "positive", "comment": "private text"},
        )

    assert missing.status_code == 401
    assert invalid.status_code == 422
    assert extra.status_code == 422
    assert gateway.feedback_calls == []


@pytest.mark.anyio
async def test_feedback_accepts_both_ratings_and_updates_one_message_safely() -> None:
    gateway = ApiCustomerChatGateway()
    configure_dependencies(gateway)
    path = f"/api/chat/conversations/{CONVERSATION_ID}/messages/{ASSISTANT_MESSAGE_ID}/feedback"
    headers = {"X-SupportPilot-Session": CUSTOMER_TOKEN}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        positive = await client.put(path, headers=headers, json={"rating": "positive"})
        repeated = await client.put(path, headers=headers, json={"rating": "positive"})
        negative = await client.put(path, headers=headers, json={"rating": "negative"})

    assert positive.json() == {
        "message_id": str(ASSISTANT_MESSAGE_ID),
        "rating": "positive",
    }
    assert repeated.status_code == 200
    assert negative.json()["rating"] == "negative"
    assert gateway.feedback_by_message == {ASSISTANT_MESSAGE_ID: "negative"}
    assert TOKEN_HASH not in positive.text + repeated.text + negative.text


@pytest.mark.anyio
async def test_feedback_rejects_wrong_message_and_session_safely() -> None:
    gateway = ApiCustomerChatGateway()
    configure_dependencies(gateway)
    wrong_message = UUID("90000000-0000-4000-8000-000000000099")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        target = await client.put(
            f"/api/chat/conversations/{CONVERSATION_ID}/messages/{wrong_message}/feedback",
            headers={"X-SupportPilot-Session": CUSTOMER_TOKEN},
            json={"rating": "positive"},
        )
        session = await client.put(
            f"/api/chat/conversations/{CONVERSATION_ID}/messages/{ASSISTANT_MESSAGE_ID}/feedback",
            headers={"X-SupportPilot-Session": "B" * 43},
            json={"rating": "positive"},
        )

    assert target.status_code == 409
    assert session.status_code == 401
    assert "hash" not in target.text + session.text


@pytest.mark.anyio
async def test_human_request_is_idempotent_and_invokes_no_ai_provider() -> None:
    gateway = ApiCustomerChatGateway()
    embedding, generation = configure_dependencies(gateway)
    path = f"/api/chat/conversations/{CONVERSATION_ID}/human-request"
    headers = {"X-SupportPilot-Session": CUSTOMER_TOKEN}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.post(path)
        first = await client.post(path, headers=headers)
        repeated = await client.post(path, headers=headers)

    assert missing.status_code == 401
    assert first.status_code == 200
    assert first.json() == repeated.json()
    assert first.json()["status"] == "human_requested"
    assert gateway.human_request_calls == 2
    assert gateway.background_triage_calls == [ESCALATION_ID, ESCALATION_ID]
    assert set(first.json()) == {"conversation_id", "status", "human_requested_at"}
    assert not any(
        value in first.text
        for value in [str(ESCALATION_ID), "triage_status", "summary", "priority", "model"]
    )
    assert embedding.calls == 0
    assert generation.calls == 0


@pytest.mark.anyio
async def test_human_requested_conversation_restores_state_and_blocks_later_turn() -> None:
    gateway = ApiCustomerChatGateway()
    embedding, generation = configure_dependencies(gateway)
    headers = {"X-SupportPilot-Session": CUSTOMER_TOKEN}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        requested = await client.post(
            f"/api/chat/conversations/{CONVERSATION_ID}/human-request",
            headers=headers,
        )
        history = await client.get(
            f"/api/chat/conversations/{CONVERSATION_ID}",
            headers=headers,
        )
        turn = await client.post(
            f"/api/chat/conversations/{CONVERSATION_ID}/turns",
            headers=headers,
            json={
                "client_message_id": str(CLIENT_MESSAGE_ID),
                "message": "How do I reset my password?",
            },
        )

    assert requested.status_code == 200
    assert history.json()["status"] == "human_requested"
    assert history.json()["human_requested_at"] == NOW.isoformat().replace("+00:00", "Z")
    assert turn.status_code == 409
    assert embedding.calls == 0
    assert generation.calls == 0


@pytest.mark.anyio
async def test_human_request_succeeds_when_background_agent_is_not_configured() -> None:
    from tests.test_escalation_triage import FakeGateway

    customer_gateway = ApiCustomerChatGateway()
    configure_dependencies(customer_gateway)
    escalation_gateway = FakeGateway()

    async def run_triage(escalation_id):
        assert customer_gateway.status == "human_requested"
        await EscalationTriageService(escalation_gateway, None).triage(escalation_id)

    app.dependency_overrides[get_background_triage_runner] = lambda: run_triage
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/chat/conversations/{CONVERSATION_ID}/human-request",
            headers={"X-SupportPilot-Session": CUSTOMER_TOKEN},
        )
    assert response.status_code == 200
    assert set(response.json()) == {"conversation_id", "status", "human_requested_at"}
    assert escalation_gateway.fail_calls[0][2] == "triage_not_configured"
    assert "triage" not in response.text and "escalation" not in response.text


def parse_sse(response_text: str) -> list[tuple[str, dict]]:
    events = []
    for frame in response_text.strip().split("\n\n"):
        lines = frame.splitlines()
        assert len(lines) == 2
        assert lines[0].startswith("event: ")
        assert lines[1].startswith("data: ")
        events.append((lines[0][7:], json.loads(lines[1][6:])))
    return events


@pytest.mark.anyio
async def test_stream_endpoint_requires_session_and_uses_safe_sse_order() -> None:
    gateway = ApiCustomerChatGateway(with_evidence=True)
    embedding, generation = configure_dependencies(gateway)
    path = f"/api/chat/conversations/{CONVERSATION_ID}/turns/stream"
    payload = {
        "client_message_id": str(CLIENT_MESSAGE_ID),
        "message": "How do I reset my password?",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.post(path, json=payload)
        response = await client.post(
            path,
            headers={"X-SupportPilot-Session": CUSTOMER_TOKEN},
            json=payload,
        )

    assert missing.status_code == 401
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-store"
    assert response.headers["x-accel-buffering"] == "no"
    events = parse_sse(response.text)
    assert [name for name, _data in events] == ["started", "delta", "delta", "complete"]
    assert "".join(data["text"] for name, data in events if name == "delta") == (
        "Use the reset link."
    )
    complete = events[-1][1]
    assert complete["message_id"] == str(ASSISTANT_MESSAGE_ID)
    assert complete["citations"][0]["source_id"] == str(SOURCE_ID)
    assert embedding.calls == 1
    assert generation.stream_calls == 1
    for forbidden in (CUSTOMER_TOKEN, TOKEN_HASH, "workspace_id", "embedding", "similarity"):
        assert forbidden not in response.text


@pytest.mark.anyio
async def test_stream_no_evidence_skips_generation_and_completes_without_deltas() -> None:
    gateway = ApiCustomerChatGateway(with_evidence=False)
    _embedding, generation = configure_dependencies(gateway)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/chat/conversations/{CONVERSATION_ID}/turns/stream",
            headers={"X-SupportPilot-Session": CUSTOMER_TOKEN},
            json={
                "client_message_id": str(CLIENT_MESSAGE_ID),
                "message": "How do I reset my password?",
            },
        )

    events = parse_sse(response.text)
    assert [name for name, _data in events] == ["started", "complete"]
    assert events[-1][1]["status"] == "insufficient_evidence"
    assert events[-1][1]["citations"] == []
    assert generation.stream_calls == 0


@pytest.mark.anyio
async def test_stream_completed_replay_emits_only_persisted_complete() -> None:
    class ReplayGateway(ApiCustomerChatGateway):
        async def begin_turn(self, conversation_id, token_hash, client_message_id, message):
            return StartedCustomerTurn(
                turn_id=TURN_ID,
                workspace_id=WORKSPACE_ID,
                conversation_id=CONVERSATION_ID,
                turn_status="completed",
                is_replay=True,
            )

    gateway = ReplayGateway()
    gateway.completed = PersistedCustomerTurn(
        turn_id=TURN_ID,
        conversation_id=CONVERSATION_ID,
        message_id=ASSISTANT_MESSAGE_ID,
        client_message_id=CLIENT_MESSAGE_ID,
        answer_status="answered",
        answer="Persisted replay.",
        citations=[],
    )
    embedding, generation = configure_dependencies(gateway)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/chat/conversations/{CONVERSATION_ID}/turns/stream",
            headers={"X-SupportPilot-Session": CUSTOMER_TOKEN},
            json={
                "client_message_id": str(CLIENT_MESSAGE_ID),
                "message": "How do I reset my password?",
            },
        )

    events = parse_sse(response.text)
    assert [name for name, _data in events] == ["complete"]
    assert events[0][1]["is_replay"] is True
    assert embedding.calls == 0
    assert generation.stream_calls == 0


@pytest.mark.anyio
async def test_processing_duplicate_fails_before_sse_and_does_not_regenerate() -> None:
    class ProcessingGateway(ApiCustomerChatGateway):
        async def begin_turn(self, conversation_id, token_hash, client_message_id, message):
            return StartedCustomerTurn(
                turn_id=TURN_ID,
                workspace_id=WORKSPACE_ID,
                conversation_id=CONVERSATION_ID,
                turn_status="processing",
                is_replay=True,
            )

    gateway = ProcessingGateway()
    embedding, generation = configure_dependencies(gateway)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/chat/conversations/{CONVERSATION_ID}/turns/stream",
            headers={"X-SupportPilot-Session": CUSTOMER_TOKEN},
            json={
                "client_message_id": str(CLIENT_MESSAGE_ID),
                "message": "How do I reset my password?",
            },
        )

    assert response.status_code == 409
    assert "text/event-stream" not in response.headers.get("content-type", "")
    assert embedding.calls == 0
    assert generation.stream_calls == 0


@pytest.mark.anyio
async def test_stream_failure_is_sanitized_and_never_emits_complete() -> None:
    class FailingGateway(ApiCustomerChatGateway):
        def __init__(self):
            super().__init__()
            self.failures = []

        async def fail_turn(self, *args):
            self.failures.append(args)

    class InvalidGeneration(ApiGenerationProvider):
        async def stream_grounded_answer(self, question, evidence):
            yield GenerationDecisionEvent(decision="answerable", evidence_ids=["E9"])
            yield GenerationAnswerDelta(text="private provider detail")

    gateway = FailingGateway()
    embedding = ApiEmbeddingProvider()
    generation = InvalidGeneration()
    app.dependency_overrides[get_customer_chat_gateway] = lambda: gateway
    app.dependency_overrides[get_embedding_provider] = lambda: embedding
    app.dependency_overrides[get_generation_provider] = lambda: generation
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/chat/conversations/{CONVERSATION_ID}/turns/stream",
            headers={"X-SupportPilot-Session": CUSTOMER_TOKEN},
            json={
                "client_message_id": str(CLIENT_MESSAGE_ID),
                "message": "How do I reset my password?",
            },
        )

    events = parse_sse(response.text)
    assert [name for name, _data in events] == ["started", "error"]
    assert events[-1][1] == {
        "code": "stream_failed",
        "message": "I couldn't complete that response right now.",
    }
    assert "private" not in response.text
    assert gateway.failures == [(TURN_ID, TOKEN_HASH, "generation_failed")]
