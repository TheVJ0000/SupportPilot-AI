import json
from uuid import UUID

import httpx
import pytest

from app.knowledge.errors import GatewayError
from app.rag.gateway import SupabaseRetrievalGateway

WORKSPACE_ID = UUID("20000000-0000-0000-0000-000000000001")
SOURCE_ID = UUID("30000000-0000-0000-0000-000000000001")
CHUNK_ID = UUID("40000000-0000-0000-0000-000000000001")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def valid_row() -> dict:
    return {
        "chunk_id": str(CHUNK_ID),
        "source_id": str(SOURCE_ID),
        "source_title": "Account Help",
        "source_type": "file",
        "chunk_index": 3,
        "content": "Use the synthetic password reset link.",
        "locator": {"kind": "pdf", "page_start": 2, "page_end": 2},
        "similarity": 0.84,
    }


@pytest.mark.anyio
async def test_gateway_calls_only_scoped_search_rpc_with_user_credentials() -> None:
    captured: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        captured = request
        return httpx.Response(200, json=[valid_row()])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabaseRetrievalGateway(
            "https://project.example.test", "publishable-key", "user-token", client
        )
        matches = await gateway.search(
            WORKSPACE_ID,
            [0.1] * 768,
            "gemini",
            "gemini-embedding-2",
            768,
            8,
        )

    assert captured is not None
    assert captured.url.path == "/rest/v1/rpc/search_knowledge_chunks"
    assert captured.headers["apikey"] == "publishable-key"
    assert captured.headers["authorization"] == "Bearer user-token"
    payload = json.loads(captured.content)
    assert payload["target_workspace_id"] == str(WORKSPACE_ID)
    assert payload["expected_provider"] == "gemini"
    assert payload["expected_model"] == "gemini-embedding-2"
    assert payload["expected_dimension"] == 768
    assert payload["match_count"] == 8
    assert set(payload) == {
        "target_workspace_id",
        "query_embedding",
        "expected_provider",
        "expected_model",
        "expected_dimension",
        "match_count",
    }
    assert matches[0].locator == valid_row()["locator"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: row.update(similarity=1.5),
        lambda row: row.update(chunk_id="not-a-uuid"),
        lambda row: row.update(source_type="unknown"),
        lambda row: row.update(locator={"kind": "pdf", "page_start": 3, "page_end": 2}),
        lambda row: row.update(embedding=[0.1]),
    ],
)
async def test_gateway_rejects_malformed_or_overbroad_results(mutation) -> None:
    row = valid_row()
    mutation(row)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[row])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabaseRetrievalGateway(
            "https://project.example.test", "publishable-key", "user-token", client
        )
        with pytest.raises(GatewayError, match="search_knowledge_chunks"):
            await gateway.search(WORKSPACE_ID, [0.1] * 768, "gemini", "gemini-embedding-2", 768, 8)


@pytest.mark.anyio
async def test_gateway_preserves_database_permission_code_without_raw_body() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"code": "42501", "message": "private SQL detail"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabaseRetrievalGateway(
            "https://project.example.test", "publishable-key", "user-token", client
        )
        with pytest.raises(GatewayError) as caught:
            await gateway.search(WORKSPACE_ID, [0.1] * 768, "gemini", "gemini-embedding-2", 768, 8)

    assert caught.value.provider_code == "42501"
    assert "private" not in str(caught.value)


@pytest.mark.anyio
async def test_gateway_rejects_non_finite_similarity() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        payload = json.dumps([valid_row()]).replace("0.84", "NaN")
        return httpx.Response(200, content=payload, headers={"content-type": "application/json"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabaseRetrievalGateway(
            "https://project.example.test", "publishable-key", "user-token", client
        )
        with pytest.raises(GatewayError, match="search_knowledge_chunks"):
            await gateway.search(WORKSPACE_ID, [0.1] * 768, "gemini", "gemini-embedding-2", 768, 8)


@pytest.mark.anyio
async def test_gateway_rejects_results_that_are_not_best_first() -> None:
    worse = valid_row()
    worse["chunk_id"] = "40000000-0000-0000-0000-000000000002"
    worse["source_id"] = "30000000-0000-0000-0000-000000000002"
    worse["similarity"] = 0.4
    better = valid_row()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[worse, better])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabaseRetrievalGateway(
            "https://project.example.test", "publishable-key", "user-token", client
        )
        with pytest.raises(GatewayError, match="search_knowledge_chunks"):
            await gateway.search(WORKSPACE_ID, [0.1] * 768, "gemini", "gemini-embedding-2", 768, 8)
