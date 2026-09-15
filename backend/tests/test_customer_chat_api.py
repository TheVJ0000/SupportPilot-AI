from datetime import UTC, datetime
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from app.ai.embeddings.factory import get_embedding_provider
from app.ai.generation.factory import get_generation_provider
from app.ai.generation.models import GroundedGenerationDecision
from app.chat.errors import CustomerChatGatewayError
from app.chat.gateway import get_customer_chat_gateway
from app.chat.models import (
    CreatedCustomerSession,
    CustomerConversationResponse,
    CustomerHistoryMessage,
    PersistedCustomerTurn,
    StartedCustomerTurn,
)
from app.chat.security import hash_customer_session_token
from app.core.config import Settings, get_settings
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

    async def generate_grounded_answer(self, question, evidence):
        self.calls += 1
        assert question == "How do I reset my password?"
        assert [item.evidence_id for item in evidence] == ["E1"]
        return GroundedGenerationDecision(
            decision="answerable",
            answer="Use the reset link.",
            evidence_ids=["E1"],
        )


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
            status="open",
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
