import inspect
import json
from copy import deepcopy
from typing import Annotated
from uuid import UUID

import httpx
import pytest
from fastapi import Depends
from pydantic import ValidationError

from app.admin import gateway as gateway_module
from app.admin.gateway import AdminOperationsGateway, get_admin_gateway
from app.admin.models import (
    Citation,
    ConversationDetail,
    ConversationPage,
    ConversationQuery,
    Dashboard,
    EscalationDetail,
    EscalationPage,
    EscalationQuery,
    Message,
    Metrics,
)
from app.auth.dependencies import get_authenticated_context, get_token_verifier
from app.auth.models import AuthenticatedRequestContext, AuthenticatedUser
from app.main import app

WS = UUID("20000000-0000-4000-8000-000000000001")
OTHER = UUID("20000000-0000-4000-8000-000000000002")
CONV = UUID("40000000-0000-4000-8000-000000000001")
ESC = UUID("50000000-0000-4000-8000-000000000001")
TIME = "2026-09-16T12:00:00Z"
ZERO = {name: 0 for name in Metrics.model_fields}
CONVERSATION = {
    "id": str(CONV),
    "status": "open",
    "created_at": TIME,
    "updated_at": TIME,
    "last_message_at": TIME,
}
ITEM = {
    **CONVERSATION,
    "message_count": 2,
    "assistant_message_count": 1,
    "feedback_positive_count": 1,
    "feedback_negative_count": 0,
    "has_escalation": False,
    "escalation_priority": None,
}
ESC_ITEM = {
    "id": str(ESC),
    "conversation_id": str(CONV),
    "trigger_reason": "human_requested",
    "status": "open",
    "triage_status": "pending",
    "category": None,
    "priority": None,
    "summary": None,
    "triage_attempts": 0,
    "created_at": TIME,
    "updated_at": TIME,
    "triaged_at": None,
    "last_error_code": None,
    "notification_status": None,
}
DASHBOARD = {
    "workspace_id": str(WS),
    "metrics": ZERO,
    "recent_conversations": [],
    "recent_escalations": [],
}
CONV_DETAIL = {
    "workspace_id": str(WS),
    "conversation": {**CONVERSATION, "human_requested_at": None},
    "messages": [],
    "escalation": None,
}
ESC_DETAIL = {
    "workspace_id": str(WS),
    "escalation": ESC_ITEM,
    "audit_runs": [],
    "notification": None,
}
PAGE = {"workspace_id": str(WS), "items": [], "next_cursor": None}
ENDPOINTS = [
    ("dashboard", "admin_dashboard_snapshot", DASHBOARD),
    ("conversations", "admin_list_conversations", PAGE),
    (f"conversations/{CONV}", "admin_get_conversation", CONV_DETAIL),
    ("escalations", "admin_list_escalations", PAGE),
    (f"escalations/{ESC}", "admin_get_escalation", ESC_DETAIL),
]


class Verifier:
    async def verify(self, token: str) -> AuthenticatedUser:
        assert token == "test-access-token"
        return AuthenticatedUser(user_id=CONV)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def reset_dependencies():
    yield
    app.dependency_overrides.clear()


def install_gateway(handler):
    app.dependency_overrides[get_token_verifier] = Verifier

    async def dependency(
        context: Annotated[AuthenticatedRequestContext, Depends(get_authenticated_context)],
    ):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            yield AdminOperationsGateway(
                "https://example.supabase.co", "publishable-demo", context.access_token, client
            )

    app.dependency_overrides[get_admin_gateway] = dependency


async def request(path: str, authorized=True):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get(
            f"/api/admin/workspaces/{WS}/{path}",
            headers={"Authorization": "Bearer test-access-token"} if authorized else {},
        )


@pytest.mark.anyio
@pytest.mark.parametrize("path,rpc,payload", ENDPOINTS)
async def test_five_reads_require_verified_bearer_and_use_caller_headers(path, rpc, payload):
    requests = []

    def handler(req):
        requests.append(req)
        assert req.url.path == f"/rest/v1/rpc/{rpc}"
        assert req.headers["apikey"] == "publishable-demo"
        assert req.headers["authorization"] == "Bearer test-access-token"
        assert json.loads(req.content)["target_workspace_id"] == str(WS)
        return httpx.Response(200, json=payload)

    install_gateway(handler)
    assert (await request(path, False)).status_code == 401
    assert not requests
    response = await request(path)
    assert response.status_code == 200
    assert response.json() == payload


@pytest.mark.anyio
@pytest.mark.parametrize("path,rpc,payload", ENDPOINTS)
@pytest.mark.parametrize("code,expected", [("42501", 403), ("P0002", 404), ("XX000", 502)])
async def test_safe_database_error_mapping(path, rpc, payload, code, expected):
    install_gateway(
        lambda req: httpx.Response(
            400, json={"code": code, "message": "private SQL and customer data"}
        )
    )
    response = await request(path)
    assert response.status_code == expected
    assert "private" not in response.text


@pytest.mark.anyio
@pytest.mark.parametrize("path,rpc,payload", ENDPOINTS)
async def test_untrusted_results_reject_extra_fields_and_other_workspaces(path, rpc, payload):
    for invalid in (
        {**payload, "workspace_id": str(OTHER)},
        {**payload, "token_hash": "synthetic-forbidden-field"},
        [],
    ):
        install_gateway(lambda req, invalid=invalid: httpx.Response(200, json=invalid))
        response = await request(path)
        assert response.status_code == 502
        assert "synthetic-forbidden-field" not in response.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    "path",
    [
        "conversations?limit=0",
        "conversations?limit=51",
        "conversations?limit=1.2",
        "conversations?status=resolved",
        "conversations?sort=SQL",
        "conversations?cursor_time=2026-09-16T12:00:00Z",
        "conversations?cursor_id=bad",
        "conversations?cursor_time=2026-09-16T12:00:00&cursor_id=" + str(CONV),
        "escalations?cursor_id=" + str(ESC),
        "escalations?priority=critical",
        "escalations?triage_status=done",
        "escalations?trigger_reason=anything",
        "escalations?filter=raw",
        "escalations?status=bad",
    ],
)
async def test_query_validation_blocks_arbitrary_filters_and_bad_cursors(path):
    calls = []
    install_gateway(lambda req: calls.append(req) or httpx.Response(200, json=PAGE))
    assert (await request(path)).status_code == 422
    assert not calls


@pytest.mark.anyio
async def test_network_and_malformed_json_errors_are_safe():
    def unavailable(req):
        raise httpx.ConnectError("internal network details", request=req)

    install_gateway(unavailable)
    assert (await request("dashboard")).status_code == 503
    install_gateway(lambda req: httpx.Response(200, content=b"not JSON"))
    assert (await request("dashboard")).status_code == 502


@pytest.mark.anyio
async def test_scoped_detail_identifiers_checked():
    install_gateway(
        lambda req: httpx.Response(
            200,
            json={**CONV_DETAIL, "conversation": {**CONV_DETAIL["conversation"], "id": str(OTHER)}},
        )
    )
    assert (await request(f"conversations/{CONV}")).status_code == 502
    install_gateway(
        lambda req: httpx.Response(
            200, json={**ESC_DETAIL, "escalation": {**ESC_ITEM, "id": str(OTHER)}}
        )
    )
    assert (await request(f"escalations/{ESC}")).status_code == 502


@pytest.mark.anyio
async def test_null_activity_cursor_and_fixed_filters_forwarded():
    def handler(req):
        params = json.loads(req.content)
        assert params == {
            "target_workspace_id": str(WS),
            "page_limit": 25,
            "status_filter": "open",
            "cursor_id": str(CONV),
            "cursor_time": None,
        }
        return httpx.Response(200, json=PAGE)

    install_gateway(handler)
    assert (await request(f"conversations?status=open&cursor_id={CONV}")).status_code == 200


@pytest.mark.anyio
async def test_escalation_filters_and_cursor_forwarded():
    def handler(req):
        params = json.loads(req.content)
        assert params["priority_filter"] == "high"
        assert params["triage_status_filter"] == "completed"
        assert params["trigger_reason_filter"] == "human_requested"
        assert params["status_filter"] == "in_progress"
        assert params["cursor_id"] == str(ESC)
        return httpx.Response(200, json=PAGE)

    install_gateway(handler)
    assert (
        await request(
            f"escalations?status=in_progress&priority=high&triage_status=completed&trigger_reason=human_requested&cursor_id={ESC}&cursor_time={TIME}"
        )
    ).status_code == 200


@pytest.mark.parametrize("value", [-1, True, "1", 1.5, None])
def test_strict_nonnegative_metrics(value):
    with pytest.raises(ValidationError):
        Dashboard.model_validate({**DASHBOARD, "metrics": {**ZERO, "total_conversations": value}})


def test_zero_metrics_and_coverage_denominator_consistency():
    assert Dashboard.model_validate(DASHBOARD).metrics.total_conversations == 0
    with pytest.raises(ValidationError):
        Metrics.model_validate({**ZERO, "ai_answered_conversations": 1})


@pytest.mark.parametrize(
    "locator",
    [
        {"kind": "pdf", "page_start": True, "page_end": 2},
        {"kind": "pdf", "page_start": 3, "page_end": 2},
        {"kind": "faq", "path": "private"},
        {"kind": "html"},
    ],
)
def test_citation_locators_are_exact_and_safe(locator):
    with pytest.raises(ValidationError):
        Citation.model_validate(
            {
                "source_id": str(CONV),
                "source_title": "Demo",
                "source_type": "file",
                "chunk_index": 0,
                "locator": locator,
            }
        )


def test_safe_transcript_and_audit_fields_are_validated():
    citation = {
        "source_id": str(CONV),
        "source_title": "Synthetic FAQ",
        "source_type": "faq",
        "chunk_index": 0,
        "locator": {"kind": "faq"},
    }
    message = {
        "id": str(CONV),
        "role": "assistant",
        "content": "<script>not HTML</script>",
        "answer_status": "answered",
        "created_at": TIME,
        "feedback": "positive",
        "citations": [citation],
    }
    assert Message.model_validate(message).content == message["content"]
    detail = ConversationDetail.model_validate({**CONV_DETAIL, "messages": [message]})
    assert detail.messages[0].feedback == "positive"
    for field in (
        "customer_session_id",
        "token_hash",
        "embedding",
        "provider_message_id",
        "recipient_emails",
    ):
        with pytest.raises(ValidationError):
            ConversationDetail.model_validate({**CONV_DETAIL, field: "forbidden"})
    invalid = deepcopy(ESC_DETAIL)
    invalid["audit_runs"] = [
        {
            "attempt_number": 1,
            "status": "failed",
            "provider": None,
            "model": None,
            "tool_name": None,
            "safe_error_code": "raw provider detail",
            "started_at": TIME,
            "completed_at": TIME,
        }
    ]
    with pytest.raises(ValidationError):
        EscalationDetail.model_validate(invalid)


@pytest.mark.parametrize(
    "model,item,timefield",
    [(ConversationPage, ITEM, "last_message_at"), (EscalationPage, ESC_ITEM, "created_at")],
)
def test_page_order_duplicates_and_cursor_consistency(model, item, timefield):
    assert model.model_validate(
        {**PAGE, "items": [item], "next_cursor": {"time": item[timefield], "id": item["id"]}}
    )
    with pytest.raises(ValidationError):
        model.model_validate({**PAGE, "items": [item, item]})
    with pytest.raises(ValidationError):
        model.model_validate(
            {**PAGE, "items": [item], "next_cursor": {"time": TIME, "id": str(OTHER)}}
        )


@pytest.mark.anyio
async def test_page_filter_and_limit_mismatches_rejected():
    for path, payload in [
        ("conversations?status=closed", {**PAGE, "items": [ITEM]}),
        (
            "conversations?limit=1",
            {**PAGE, "items": [ITEM], "next_cursor": {"time": TIME, "id": str(OTHER)}},
        ),
        ("escalations?status=closed", {**PAGE, "items": [ESC_ITEM]}),
    ]:
        install_gateway(lambda req, payload=payload: httpx.Response(200, json=payload))
        assert (await request(path)).status_code == 502


@pytest.mark.anyio
async def test_workspace_uuid_validation():
    install_gateway(lambda req: httpx.Response(200, json=DASHBOARD))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/admin/workspaces/not-a-uuid/dashboard",
            headers={"Authorization": "Bearer test-access-token"},
        )
    assert response.status_code == 422


def test_admin_gateway_has_no_privileged_key_or_generic_public_proxy():
    source = inspect.getsource(gateway_module)
    assert "supabase_secret_key" not in source.lower()
    assert "service_role" not in source
    assert not hasattr(AdminOperationsGateway, "rpc")
    assert ConversationQuery(cursor_id=CONV).cursor_time is None
    with pytest.raises(ValidationError):
        EscalationQuery(cursor_id=ESC)


@pytest.mark.parametrize(
    "timestamp", [True, 1750000000, "1750000000", "2026-09-16T12:00:00", "invalid"]
)
def test_rpc_timestamps_require_iso_and_timezone(timestamp):
    with pytest.raises(ValidationError):
        ConversationPage.model_validate({**PAGE, "items": [{**ITEM, "created_at": timestamp}]})


@pytest.mark.anyio
async def test_non_json_error_and_nested_provider_internals_rejected():
    install_gateway(lambda req: httpx.Response(500, content=b"private SQL details"))
    response = await request("dashboard")
    assert response.status_code == 502 and "private" not in response.text
    payload = deepcopy(ESC_DETAIL)
    payload["notification"] = {
        "status": "pending",
        "attempts": 0,
        "provider": None,
        "last_error_code": None,
        "sent_at": None,
        "created_at": TIME,
        "updated_at": TIME,
        "provider_message_id": "private-provider-id",
    }
    install_gateway(lambda req: httpx.Response(200, json=payload))
    assert (await request(f"escalations/{ESC}")).status_code == 502
