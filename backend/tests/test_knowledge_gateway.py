import inspect
from uuid import UUID

import httpx
import pytest

from app.knowledge import gateway as gateway_module
from app.knowledge.errors import GatewayError
from app.knowledge.gateway import SupabaseKnowledgeGateway

SOURCE_ID = UUID("30000000-0000-0000-0000-000000000001")
WORKSPACE_ID = UUID("20000000-0000-0000-0000-000000000001")
STORAGE_PATH = f"{WORKSPACE_ID}/{SOURCE_ID}/{SOURCE_ID}.txt"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_gateway_accepts_no_secret_key_credential() -> None:
    parameters = inspect.signature(SupabaseKnowledgeGateway).parameters

    assert "publishable_key" in parameters
    assert "access_token" in parameters
    assert all("secret" not in name for name in parameters)


@pytest.mark.anyio
async def test_gateway_uses_publishable_key_and_user_token_for_scoped_rpc() -> None:
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(
            200,
            json=[
                {
                    "source_id": str(SOURCE_ID),
                    "workspace_id": str(WORKSPACE_ID),
                    "source_type": "faq",
                    "storage_path": None,
                    "original_filename": None,
                    "mime_type": None,
                    "byte_size": None,
                    "faq_question": "How do refunds work?",
                    "faq_answer": "Use the returns form.",
                }
            ],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabaseKnowledgeGateway(
            "https://project.example.test",
            "publishable-test-key",
            "user-access-token",
            client,
        )
        source = await gateway.begin_extraction(SOURCE_ID)

    assert source.source_id == SOURCE_ID
    assert captured_request is not None
    assert captured_request.url.path == "/rest/v1/rpc/begin_knowledge_extraction"
    assert captured_request.headers["apikey"] == "publishable-test-key"
    assert captured_request.headers["authorization"] == "Bearer user-access-token"
    assert b"workspace" not in captured_request.content


@pytest.mark.anyio
async def test_gateway_downloads_exact_private_path_with_user_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert (
            request.url.path == f"/storage/v1/object/authenticated/knowledge-files/{STORAGE_PATH}"
        )
        assert request.headers["authorization"] == "Bearer user-access-token"
        assert request.headers["apikey"] == "publishable-test-key"
        return httpx.Response(200, content=b"private source")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabaseKnowledgeGateway(
            "https://project.example.test",
            "publishable-test-key",
            "user-access-token",
            client,
        )
        content = await gateway.download_source(STORAGE_PATH)

    assert content == b"private source"


@pytest.mark.anyio
async def test_gateway_rejects_oversized_download_stream(monkeypatch) -> None:
    monkeypatch.setattr(gateway_module, "MAX_SOURCE_BYTES", 10)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 11)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabaseKnowledgeGateway(
            "https://project.example.test", "publishable", "user-token", client
        )
        with pytest.raises(GatewayError, match="download_too_large"):
            await gateway.download_source(STORAGE_PATH)


@pytest.mark.anyio
async def test_gateway_maps_download_failure_without_provider_body() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "sensitive provider detail"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabaseKnowledgeGateway(
            "https://project.example.test", "publishable", "user-token", client
        )
        with pytest.raises(GatewayError) as caught:
            await gateway.download_source(STORAGE_PATH)

    assert str(caught.value) == "download_source"
    assert "sensitive" not in str(caught.value)
