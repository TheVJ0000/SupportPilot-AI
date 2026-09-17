import json

import httpx
import pytest
from test_admin_operations import OTHER, WS, install_gateway, request

from app.main import app

PUBLIC_ID = "10000000-0000-4000-8000-000000000001"
CONFIG = {
    "workspace_id": str(WS),
    "workspace_name": "Synthetic Store",
    "public_id": PUBLIC_ID,
    "is_enabled": True,
}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def reset_dependencies():
    yield
    app.dependency_overrides.clear()


async def toggle(body, authorized=True):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.patch(
            f"/api/admin/workspaces/{WS}/widget",
            json=body,
            headers={"Authorization": "Bearer test-access-token"} if authorized else {},
        )


@pytest.mark.anyio
async def test_widget_read_requires_auth_and_fixed_rpc_caller_headers():
    calls = []

    def handler(req):
        calls.append(req)
        assert req.url.path == "/rest/v1/rpc/admin_get_widget_config"
        assert json.loads(req.content) == {"target_workspace_id": str(WS)}
        assert req.headers["apikey"] == "publishable-demo"
        assert req.headers["Authorization"] == "Bearer test-access-token"
        return httpx.Response(200, json=CONFIG)

    install_gateway(handler)
    assert (await request("widget", False)).status_code == 401
    assert not calls
    response = await request("widget")
    assert response.status_code == 200
    assert response.json() == CONFIG


@pytest.mark.anyio
@pytest.mark.parametrize("enabled", [True, False])
async def test_widget_toggle_fixed_rpc_and_verified_jwt(enabled):
    calls = []

    def handler(req):
        calls.append(req)
        assert req.url.path == "/rest/v1/rpc/admin_set_widget_enabled"
        assert req.headers["apikey"] == "publishable-demo"
        assert req.headers["Authorization"] == "Bearer test-access-token"
        assert json.loads(req.content) == {
            "target_workspace_id": str(WS),
            "expected_is_enabled": not enabled,
            "new_is_enabled": enabled,
        }
        return httpx.Response(200, json={**CONFIG, "is_enabled": enabled})

    install_gateway(handler)
    body = {"expected_enabled": not enabled, "enabled": enabled}
    assert (await toggle(body, False)).status_code == 401
    assert not calls
    response = await toggle(body)
    assert response.status_code == 200
    assert response.json()["is_enabled"] is enabled


@pytest.mark.anyio
@pytest.mark.parametrize("write", [False, True])
@pytest.mark.parametrize(
    "code,status",
    [
        ("28000", 401),
        ("42501", 403),
        ("P0002", 404),
        ("40001", 409),
        ("55000", 409),
        ("XX000", 502),
    ],
)
async def test_safe_widget_errors(write, code, status):
    install_gateway(
        lambda req: httpx.Response(
            400, json={"code": code, "message": "private SQL/provider payload"}
        )
    )
    response = (
        await toggle({"expected_enabled": True, "enabled": False})
        if write
        else await request("widget")
    )
    assert response.status_code == (502 if not write and status == 409 else status)
    assert "private" not in response.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"enabled": False},
        {"expected_enabled": True, "enabled": "false"},
        {"expected_enabled": 1, "enabled": False},
        {"expected_enabled": None, "enabled": False},
        {"expected_enabled": True, "enabled": False, "public_id": PUBLIC_ID},
    ],
)
async def test_strict_widget_body_never_calls_rpc(body):
    calls = []
    install_gateway(lambda req: calls.append(req) or httpx.Response(200, json=CONFIG))
    assert (await toggle(body)).status_code == 422
    assert not calls


@pytest.mark.anyio
@pytest.mark.parametrize(
    "payload",
    [
        [],
        {**CONFIG, "workspace_id": str(OTHER)},
        {**CONFIG, "public_id": "not-uuid"},
        {**CONFIG, "is_enabled": 1},
        {**CONFIG, "workspace_name": ""},
        {**CONFIG, "secret_key": "forbidden"},
    ],
)
async def test_malformed_widget_config_rejected(payload):
    install_gateway(lambda req: httpx.Response(200, json=payload))
    assert (await request("widget")).status_code == 502


@pytest.mark.anyio
async def test_toggle_wrong_returned_state_rejected():
    install_gateway(lambda req: httpx.Response(200, json=CONFIG))
    assert (await toggle({"expected_enabled": True, "enabled": False})).status_code == 502


@pytest.mark.anyio
@pytest.mark.parametrize("write", [False, True])
async def test_widget_transport_failure_safe_503(write):
    def handler(req):
        raise httpx.ConnectError("private network detail", request=req)

    install_gateway(handler)
    response = (
        await toggle({"expected_enabled": True, "enabled": False})
        if write
        else await request("widget")
    )
    assert response.status_code == 503
    assert "private" not in response.text
