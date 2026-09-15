import json
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest

from app.chat.errors import CustomerChatGatewayError
from app.chat.gateway import SupabaseCustomerChatGateway
from app.rag.models import TrustedCitation

PUBLIC_ID = UUID("10000000-0000-4000-8000-000000000001")
WORKSPACE_ID = UUID("20000000-0000-4000-8000-000000000001")
SESSION_ID = UUID("30000000-0000-4000-8000-000000000001")
CONVERSATION_ID = UUID("40000000-0000-4000-8000-000000000001")
CLIENT_MESSAGE_ID = UUID("50000000-0000-4000-8000-000000000001")
TURN_ID = UUID("60000000-0000-4000-8000-000000000001")
SOURCE_ID = UUID("70000000-0000-4000-8000-000000000001")
CHUNK_ID = UUID("80000000-0000-4000-8000-000000000001")
TOKEN_HASH = "a" * 64
SECRET_KEY = "synthetic-server-secret-key"
EXPIRES_AT = datetime(2026, 9, 22, tzinfo=UTC)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def citation() -> TrustedCitation:
    return TrustedCitation(
        source_id=SOURCE_ID,
        source_title="Account Help",
        source_type="file",
        chunk_index=2,
        locator={"kind": "pdf", "page_start": 3, "page_end": 3},
    )


def retrieval_row() -> dict:
    return {
        "chunk_id": str(CHUNK_ID),
        "source_id": str(SOURCE_ID),
        "source_title": "Account Help",
        "source_type": "file",
        "chunk_index": 2,
        "content": "Use the reset link.",
        "locator": {"kind": "pdf", "page_start": 3, "page_end": 3},
        "similarity": 0.87,
    }


@pytest.mark.anyio
async def test_secret_gateway_uses_only_apikey_and_hash_for_session_creation() -> None:
    captured: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        captured = request
        return httpx.Response(
            200,
            json=[
                {
                    "customer_session_id": str(SESSION_ID),
                    "conversation_id": str(CONVERSATION_ID),
                    "workspace_id": str(WORKSPACE_ID),
                    "workspace_name": "Demo Workspace",
                    "expires_at": EXPIRES_AT.isoformat(),
                }
            ],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabaseCustomerChatGateway("https://project.example.test", SECRET_KEY, client)
        created = await gateway.create_session(PUBLIC_ID, TOKEN_HASH, EXPIRES_AT)

    assert captured is not None
    assert captured.url.path == "/rest/v1/rpc/create_customer_chat_session"
    assert captured.headers["apikey"] == SECRET_KEY
    assert "authorization" not in captured.headers
    payload = json.loads(captured.content)
    assert payload == {
        "target_public_id": str(PUBLIC_ID),
        "session_token_hash": TOKEN_HASH,
        "session_expires_at": EXPIRES_AT.isoformat(),
    }
    assert '"session_token"' not in captured.content.decode()
    assert created.workspace_id == WORKSPACE_ID
    assert SECRET_KEY not in repr(gateway)


@pytest.mark.anyio
async def test_turn_and_retrieval_rpcs_never_accept_a_workspace_from_the_caller() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("begin_customer_chat_turn"):
            return httpx.Response(
                200,
                json=[
                    {
                        "turn_id": str(TURN_ID),
                        "workspace_id": str(WORKSPACE_ID),
                        "conversation_id": str(CONVERSATION_ID),
                        "turn_status": "processing",
                        "is_replay": False,
                    }
                ],
            )
        return httpx.Response(200, json=[retrieval_row()])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabaseCustomerChatGateway("https://project.example.test", SECRET_KEY, client)
        await gateway.begin_turn(CONVERSATION_ID, TOKEN_HASH, CLIENT_MESSAGE_ID, "Question?")
        matches = await gateway.search_knowledge(
            CONVERSATION_ID,
            TOKEN_HASH,
            [0.1] * 768,
            "gemini",
            "gemini-embedding-2",
            768,
            8,
        )

    begin_payload = json.loads(requests[0].content)
    search_payload = json.loads(requests[1].content)
    assert set(begin_payload) == {
        "target_conversation_id",
        "session_token_hash",
        "target_client_message_id",
        "message_content",
    }
    assert set(search_payload) == {
        "target_conversation_id",
        "session_token_hash",
        "query_embedding",
        "expected_provider",
        "expected_model",
        "expected_dimension",
        "match_count",
    }
    assert "workspace_id" not in begin_payload
    assert "workspace_id" not in search_payload
    assert matches[0].source_id == SOURCE_ID


@pytest.mark.anyio
async def test_completion_sends_only_bounded_answer_and_trusted_citation_snapshot() -> None:
    captured: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        captured = request
        return httpx.Response(200, json=True)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabaseCustomerChatGateway("https://project.example.test", SECRET_KEY, client)
        await gateway.complete_turn(
            TURN_ID,
            TOKEN_HASH,
            "answered",
            "Use the reset link.",
            [citation()],
        )

    assert captured is not None
    payload = json.loads(captured.content)
    assert set(payload) == {
        "target_turn_id",
        "session_token_hash",
        "submitted_answer_status",
        "answer_content",
        "citation_payload",
    }
    assert payload["citation_payload"] == [citation().model_dump(mode="json")]
    assert "embedding" not in captured.content.decode()
    assert "storage_path" not in captured.content.decode()


@pytest.mark.anyio
async def test_gateway_rejects_unapproved_rpc_before_network_access() -> None:
    requests = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabaseCustomerChatGateway("https://project.example.test", SECRET_KEY, client)
        with pytest.raises(CustomerChatGatewayError, match="unsupported_customer_chat_rpc"):
            await gateway._rpc("arbitrary_table_operation", {})  # type: ignore[arg-type]

    assert requests == 0


@pytest.mark.anyio
async def test_gateway_errors_preserve_only_a_safe_code() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"code": "28000", "message": "raw token and secret provider response"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabaseCustomerChatGateway("https://project.example.test", SECRET_KEY, client)
        with pytest.raises(CustomerChatGatewayError) as caught:
            await gateway.get_conversation(CONVERSATION_ID, TOKEN_HASH)

    assert caught.value.provider_code == "28000"
    assert "raw token" not in str(caught.value)
    assert SECRET_KEY not in str(caught.value)
