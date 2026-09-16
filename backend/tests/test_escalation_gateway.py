import json

import httpx
import pytest

from app.ai.triage.models import CreateEscalationArguments
from app.core.config import Settings
from app.escalations.background import get_background_triage_runner
from app.escalations.gateway import (
    ALLOWED_ESCALATION_RPCS,
    EscalationGatewayError,
    SupabaseEscalationGateway,
)
from tests.test_escalation_triage import ESCALATION_ID, RUN_ID, begun


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_gateway_has_exact_rpc_allowlist_and_no_generic_privileged_queries():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("begin_escalation_triage"):
            return httpx.Response(200, json=begun().model_dump(mode="json"))
        return httpx.Response(200, json=True)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabaseEscalationGateway(
            "https://project.example.test", "synthetic-server-key", client
        )
        result = await gateway.begin_triage(ESCALATION_ID)
        args = CreateEscalationArguments(
            category="billing", priority="high", summary="Unresolved duplicate charge."
        )
        await gateway.complete_triage(ESCALATION_ID, RUN_ID, args, "gemini", "gemini-3.8-flash")
        await gateway.fail_triage(ESCALATION_ID, RUN_ID, "triage_failed")
        with pytest.raises(EscalationGatewayError):
            await gateway._rpc("delete_database", {})
    assert result.triage_run_id == RUN_ID
    assert ALLOWED_ESCALATION_RPCS == {
        "begin_escalation_triage",
        "complete_escalation_triage",
        "fail_escalation_triage",
    }
    assert len(requests) == 3
    assert json.loads(requests[0].content) == {"target_escalation_id": str(ESCALATION_ID)}
    assert json.loads(requests[1].content) == {
        "target_escalation_id": str(ESCALATION_ID),
        "target_triage_run_id": str(RUN_ID),
        "submitted_category": "billing",
        "submitted_priority": "high",
        "submitted_summary": "Unresolved duplicate charge.",
        "submitted_provider": "gemini",
        "submitted_model": "gemini-3.8-flash",
    }
    assert all(request.headers["apikey"] == "synthetic-server-key" for request in requests)
    assert all("authorization" not in request.headers for request in requests)
    assert all("session_token" not in request.content.decode() for request in requests)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, json={"message": "raw private SQL with synthetic secret"}),
        httpx.Response(200, text="malformed raw private response"),
        httpx.Response(200, json={}),
        httpx.Response(200, json=begun().model_dump(mode="json") | {"escalation_id": str(RUN_ID)}),
        httpx.Response(200, json=begun().model_dump(mode="json") | {"token_hash": "synthetic"}),
    ],
)
async def test_gateway_does_not_expose_provider_errors_or_accept_mismatched_records(response):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response)) as client:
        gateway = SupabaseEscalationGateway(
            "https://project.example.test", "synthetic-server-key", client
        )
        with pytest.raises(EscalationGatewayError) as caught:
            await gateway.begin_triage(ESCALATION_ID)
    assert "private" not in str(caught.value) and "synthetic" not in str(caught.value)


@pytest.mark.anyio
async def test_background_owns_client_and_marks_missing_agent_failed(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("begin_escalation_triage"):
            return httpx.Response(200, json=begun().model_dump(mode="json"))
        return httpx.Response(200, json=True)

    client_class = httpx.AsyncClient
    client = client_class(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("app.escalations.background.httpx.AsyncClient", lambda **_: client)
    settings = Settings(
        _env_file=None,
        supabase_url="https://project.example.test",
        supabase_secret_key="synthetic-server-key",
        gemini_api_key=None,
    )
    await get_background_triage_runner(settings)(ESCALATION_ID)
    assert client.is_closed
    assert len(requests) == 2
    assert json.loads(requests[1].content)["submitted_error_code"] == "triage_not_configured"


@pytest.mark.anyio
async def test_background_storage_failure_is_safe(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("private synthetic credential", request=request)

    client_class = httpx.AsyncClient
    client = client_class(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("app.escalations.background.httpx.AsyncClient", lambda **_: client)
    settings = Settings(
        _env_file=None,
        supabase_url="https://project.example.test",
        supabase_secret_key="synthetic-server-key",
        gemini_api_key=None,
    )
    await get_background_triage_runner(settings)(ESCALATION_ID)
    assert client.is_closed
