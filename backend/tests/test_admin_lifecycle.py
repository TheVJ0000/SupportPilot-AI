import json
from copy import deepcopy

import httpx
import pytest
from pydantic import ValidationError
from test_admin_operations import (
    CONV,
    CONV_DETAIL,
    ESC,
    ESC_DETAIL,
    OTHER,
    TIME,
    WS,
    ZERO,
    install_gateway,
)

from app.admin.models import ConversationRecord, Metrics
from app.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def clear_dependencies():
    yield
    app.dependency_overrides.clear()


async def patch(path, body, authorized=True):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.patch(
            f"/api/admin/workspaces/{WS}/{path}",
            json=body,
            headers={"Authorization": "Bearer test-access-token"} if authorized else {},
        )


CONVERSATION_PATH = f"conversations/{CONV}/resolution"
ESCALATION_PATH = f"escalations/{ESC}/status"
RESOLVE = {
    "expected_status": "open",
    "expected_resolution_outcome": "unresolved",
    "action": "resolve",
}
START = {"expected_status": "open", "status": "in_progress"}


@pytest.mark.anyio
@pytest.mark.parametrize(
    "action,human",
    [
        ("resolve", False),
        ("close_unresolved", False),
        ("resolve", True),
        ("reopen", False),
        ("reopen", True),
    ],
)
async def test_conversation_actions_use_fixed_rpc_and_caller_jwt(action, human):
    payload = deepcopy(CONV_DETAIL)
    record = payload["conversation"]
    record.update(
        status=("human_requested" if human else "open") if action == "reopen" else "closed",
        resolution_outcome={
            "resolve": "resolved",
            "close_unresolved": "closed_unresolved",
            "reopen": "unresolved",
        }[action],
        human_requested_at=TIME if human else None,
        resolved_at=TIME if action == "resolve" else None,
        closed_at=None if action == "reopen" else TIME,
    )
    request = {
        "expected_status": "closed"
        if action == "reopen"
        else "human_requested"
        if human
        else "open",
        "expected_resolution_outcome": "resolved" if action == "reopen" else "unresolved",
        "action": action,
    }
    calls = []

    def handler(req):
        calls.append(req)
        assert req.url.path == "/rest/v1/rpc/admin_set_conversation_resolution"
        assert req.headers["apikey"] == "publishable-demo"
        assert req.headers["authorization"] == "Bearer test-access-token"
        assert json.loads(req.content) == {
            "target_workspace_id": str(WS),
            "target_conversation_id": str(CONV),
            "expected_status": request["expected_status"],
            "expected_resolution_outcome": request["expected_resolution_outcome"],
            "requested_action": action,
        }
        return httpx.Response(200, json=payload)

    install_gateway(handler)
    assert (await patch(CONVERSATION_PATH, request, False)).status_code == 401
    assert not calls
    response = await patch(CONVERSATION_PATH, request)
    assert response.status_code == 200
    assert response.json() == payload


@pytest.mark.anyio
@pytest.mark.parametrize(
    "expected,status",
    [
        ("open", "in_progress"),
        ("in_progress", "open"),
        ("open", "resolved"),
        ("in_progress", "resolved"),
        ("resolved", "open"),
        ("open", "closed"),
        ("in_progress", "closed"),
        ("resolved", "closed"),
        ("closed", "open"),
    ],
)
async def test_escalation_actions_use_fixed_rpc_and_caller_jwt(expected, status):
    payload = deepcopy(ESC_DETAIL)
    payload["escalation"]["status"] = status

    def handler(req):
        assert req.url.path == "/rest/v1/rpc/admin_set_escalation_status"
        assert req.headers["apikey"] == "publishable-demo"
        assert req.headers["authorization"] == "Bearer test-access-token"
        assert json.loads(req.content) == {
            "target_workspace_id": str(WS),
            "target_escalation_id": str(ESC),
            "expected_current_status": expected,
            "new_status": status,
        }
        return httpx.Response(200, json=payload)

    install_gateway(handler)
    assert (await patch(ESCALATION_PATH, START, False)).status_code == 401
    response = await patch(ESCALATION_PATH, {"expected_status": expected, "status": status})
    assert response.status_code == 200
    assert response.json() == payload


@pytest.mark.anyio
@pytest.mark.parametrize("path,body", [(CONVERSATION_PATH, RESOLVE), (ESCALATION_PATH, START)])
@pytest.mark.parametrize(
    "code,status",
    [
        ("42501", 403),
        ("P0002", 404),
        ("40001", 409),
        ("55000", 409),
        ("28000", 401),
        ("XX000", 502),
    ],
)
async def test_safe_mutation_errors(path, body, code, status):
    install_gateway(
        lambda req: httpx.Response(
            400, json={"code": code, "message": "private SQL/customer payload"}
        )
    )
    response = await patch(path, body)
    assert response.status_code == status
    assert "private" not in response.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    "path,body",
    [
        (CONVERSATION_PATH, {**RESOLVE, "action": "delete"}),
        (CONVERSATION_PATH, {**RESOLVE, "expected_status": "resolved"}),
        (CONVERSATION_PATH, {**RESOLVE, "expected_resolution_outcome": "ai_resolved"}),
        (CONVERSATION_PATH, {**RESOLVE, "notes": "private"}),
        (CONVERSATION_PATH, {"action": "resolve"}),
        (ESCALATION_PATH, {**START, "status": "paused"}),
        (ESCALATION_PATH, {**START, "expected_status": None}),
        (ESCALATION_PATH, {**START, "rpc": "arbitrary"}),
    ],
)
async def test_strict_mutation_requests(path, body):
    calls = []
    install_gateway(lambda req: calls.append(req) or httpx.Response(200, json=ESC_DETAIL))
    assert (await patch(path, body)).status_code == 422
    assert not calls


@pytest.mark.anyio
@pytest.mark.parametrize(
    "path,body,payload",
    [(CONVERSATION_PATH, RESOLVE, CONV_DETAIL), (ESCALATION_PATH, START, ESC_DETAIL)],
)
async def test_reject_wrong_server_state_identifiers_and_malformed_output(path, body, payload):
    for invalid in [
        payload,
        {**payload, "workspace_id": str(OTHER)},
        {**payload, "secret": "forbidden"},
        [],
    ]:
        install_gateway(lambda req, invalid=invalid: httpx.Response(200, json=invalid))
        assert (await patch(path, body)).status_code == 502
    invalid = deepcopy(payload)
    invalid["conversation" if path == CONVERSATION_PATH else "escalation"]["id"] = str(OTHER)
    install_gateway(lambda req: httpx.Response(200, json=invalid))
    assert (await patch(path, body)).status_code == 502


@pytest.mark.parametrize(
    "status,outcome,resolved,closed",
    [
        ("open", "resolved", TIME, TIME),
        ("closed", "unresolved", None, None),
        ("human_requested", "unresolved", None, TIME),
        ("closed", "resolved", None, TIME),
        ("closed", "closed_unresolved", TIME, TIME),
    ],
)
def test_rpc_resolution_state_consistency(status, outcome, resolved, closed):
    with pytest.raises(ValidationError):
        ConversationRecord.model_validate(
            {
                **CONV_DETAIL["conversation"],
                "status": status,
                "resolution_outcome": outcome,
                "resolved_at": resolved,
                "closed_at": closed,
            }
        )


def test_resolution_metrics_are_bounded_and_not_derived_from_ai():
    metrics = Metrics.model_validate(
        {
            **ZERO,
            "total_conversations": 4,
            "resolved_conversations": 1,
            "closed_unresolved_conversations": 1,
            "ai_answered_conversations": 3,
        }
    )
    assert metrics.resolved_conversations == 1
    with pytest.raises(ValidationError):
        Metrics.model_validate(
            {
                **ZERO,
                "total_conversations": 1,
                "resolved_conversations": 1,
                "closed_unresolved_conversations": 1,
            }
        )


@pytest.mark.anyio
async def test_patch_cors_is_explicit_and_accepts_browser_preflight():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.options(
            f"/api/admin/workspaces/{WS}/{CONVERSATION_PATH}",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "PATCH",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-methods"] == "GET, POST, PATCH"
