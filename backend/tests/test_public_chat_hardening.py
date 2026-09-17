import json
from datetime import UTC, datetime

import httpx
import pytest
from test_customer_chat_api import (
    ASSISTANT_MESSAGE_ID,
    CLIENT_MESSAGE_ID,
    CONVERSATION_ID,
    CUSTOMER_TOKEN,
    PUBLIC_ID,
    ApiCustomerChatGateway,
    configure_dependencies,
)
from test_escalation_automation import FakeLister

from app.chat.errors import CustomerChatGatewayError
from app.chat.gateway import SupabaseCustomerChatGateway
from app.chat.public_contract import PUBLIC_BODY_MAX_BYTES, PublicChatProtection
from app.escalations.automation import EscalationAutomationWorker
from app.main import app

SESSION_PATH = f"/api/chat/{PUBLIC_ID}/session"
CONVERSATION_PATH = f"/api/chat/conversations/{CONVERSATION_ID}"
TURN_BODY = {"client_message_id": str(CLIENT_MESSAGE_ID), "message": "How do I reset my password?"}
ENDPOINTS = [
    ("POST", SESSION_PATH, None),
    ("GET", CONVERSATION_PATH, None),
    ("POST", CONVERSATION_PATH + "/turns", TURN_BODY),
    ("POST", CONVERSATION_PATH + "/turns/stream", TURN_BODY),
    (
        "PUT",
        CONVERSATION_PATH + f"/messages/{ASSISTANT_MESSAGE_ID}/feedback",
        {"rating": "positive"},
    ),
    ("POST", CONVERSATION_PATH + "/human-request", None),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


class LimitedGateway(ApiCustomerChatGateway):
    async def create_session(self, *args):
        raise CustomerChatGatewayError("create_customer_chat_session", "PT429", 37)

    async def get_conversation(self, *args, public_request=False):
        assert public_request
        raise CustomerChatGatewayError("get_customer_conversation_history", "PT429", 37)

    async def begin_turn(self, *args):
        raise CustomerChatGatewayError("begin_customer_chat_turn", "PT429", 37)

    async def set_feedback(self, *args):
        raise CustomerChatGatewayError("set_customer_message_feedback", "PT429", 37)

    async def request_human_support(self, *args):
        raise CustomerChatGatewayError("request_customer_human_support", "PT429", 37)


@pytest.mark.anyio
@pytest.mark.parametrize("method,path,body", ENDPOINTS)
async def test_http_429_contract_precedes_streaming_and_all_ai(method, path, body):
    embedding, generation = configure_dependencies(LimitedGateway())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(
            method, path, json=body, headers={"X-SupportPilot-Session": CUSTOMER_TOKEN}
        )
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "37"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "application/json" in response.headers["Content-Type"]
    assert response.json() == {
        "error": {
            "code": "rate_limited",
            "message": "Too many requests. Please try again shortly.",
            "retry_after_seconds": 37,
        }
    }
    assert embedding.calls == generation.calls == generation.stream_calls == 0


@pytest.mark.anyio
@pytest.mark.parametrize(
    "code,status,expected",
    [
        ("28000", 401, "invalid_session"),
        ("42501", 409, "chat_unavailable"),
        ("55000", 409, "conversation_not_open"),
        ("22023", 400, "invalid_request"),
        ("P0002", 404, "conversation_unavailable"),
        ("XX000", 502, "temporarily_unavailable"),
    ],
)
async def test_allowlisted_errors_hide_all_provider_details(code, status, expected):
    class FailedGateway(ApiCustomerChatGateway):
        async def begin_turn(self, *args):
            raise CustomerChatGatewayError("begin_customer_chat_turn", code)

    configure_dependencies(FailedGateway())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            CONVERSATION_PATH + "/turns",
            json=TURN_BODY,
            headers={"X-SupportPilot-Session": CUSTOMER_TOKEN},
        )
    assert response.status_code == status
    assert response.json()["error"]["code"] == expected
    assert set(response.json()) == {"error"}
    assert code not in response.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    "body",
    [b"{bad json", b"[]", b'{"scope":"turn_hour"}', b'{"message":null}', b'{"message":123}', b"{}"],
)
async def test_malformed_and_client_limiter_fields_use_safe_validation(body):
    configure_dependencies(ApiCustomerChatGateway())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            CONVERSATION_PATH + "/turns",
            content=body,
            headers={"X-SupportPilot-Session": CUSTOMER_TOKEN, "Content-Type": "application/json"},
        )
    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "invalid_request", "message": "The request is invalid."}
    }
    assert "detail" not in response.text


@pytest.mark.anyio
@pytest.mark.parametrize("field", ["limit", "window", "scope", "subject", "workspace_id"])
async def test_session_body_cannot_set_limiter_fields(field):
    configure_dependencies(ApiCustomerChatGateway())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(SESSION_PATH, json={field: "attacker"})
    assert response.status_code == 422


@pytest.mark.anyio
@pytest.mark.parametrize("method,path,body", [row for row in ENDPOINTS if row[0] != "GET"])
async def test_oversized_body_is_rejected_before_dependencies(method, path, body):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(
            method,
            path,
            content=b"x" * (PUBLIC_BODY_MAX_BYTES + 1),
            headers={"Content-Type": "application/json", "Origin": "http://localhost:5173"},
        )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "invalid_request"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"


@pytest.mark.anyio
@pytest.mark.parametrize("declared_length", [None, b"1", b"invalid"])
async def test_asgi_actual_chunk_bytes_are_bounded_without_trusting_content_length(declared_length):
    reached = []

    async def downstream(scope, receive, send):
        reached.append(True)

    headers = [(b"content-type", b"application/json")]
    if declared_length is not None:
        headers.append((b"content-length", declared_length))
    scope = {"type": "http", "method": "POST", "path": SESSION_PATH, "headers": headers}
    chunks = iter(
        [
            {"type": "http.request", "body": b"x" * 8192, "more_body": True},
            {"type": "http.request", "body": b"x" * 8193, "more_body": False},
        ]
    )

    async def receive():
        return next(chunks)

    messages = []

    async def send(message):
        messages.append(message)

    await PublicChatProtection(downstream)(scope, receive, send)
    assert messages[0]["status"] == 413
    assert not reached
    assert json.loads(messages[1]["body"])["error"]["code"] == "invalid_request"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "content_type", ["text/plain", "application/x-www-form-urlencoded", "application/jsonp", ""]
)
async def test_json_mutations_require_json(content_type):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            CONVERSATION_PATH + "/turns",
            content=json.dumps(TURN_BODY),
            headers={"Content-Type": content_type},
        )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "invalid_request"


@pytest.mark.anyio
async def test_valid_empty_session_and_human_requests_and_success_headers():
    configure_dependencies(ApiCustomerChatGateway())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        session = await client.post(SESSION_PATH)
        human = await client.post(
            CONVERSATION_PATH + "/human-request", headers={"X-SupportPilot-Session": CUSTOMER_TOKEN}
        )
    for response in [session, human]:
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.anyio
async def test_business_api_errors_and_large_non_public_requests_are_not_rewritten():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/auth/me")
    assert response.status_code == 401 and "detail" in response.json()
    reached = []

    async def downstream(scope, receive, send):
        reached.append(True)

    await PublicChatProtection(downstream)(
        {"type": "http", "method": "POST", "path": "/api/knowledge/upload", "headers": []},
        None,
        None,
    )
    assert reached


@pytest.mark.anyio
@pytest.mark.parametrize("seconds", [0, -1, 3601, True, "3", None, 3, 3600])
async def test_gateway_only_accepts_bounded_retry_metadata(seconds):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                429,
                json={
                    "code": "PT429",
                    "message": "private SQL",
                    "details": json.dumps({"retry_after_seconds": seconds}),
                },
            )
        )
    ) as client:
        gateway = SupabaseCustomerChatGateway(
            "https://example.test", "synthetic-server-key", client
        )
        with pytest.raises(CustomerChatGatewayError) as caught:
            await gateway.create_session(PUBLIC_ID, "a" * 64, datetime.now(UTC))
    assert caught.value.retry_after_seconds == (
        seconds if type(seconds) is int and 1 <= seconds <= 3600 else 60
    )
    assert "private" not in str(caught.value)


@pytest.mark.anyio
async def test_cleanup_is_low_frequency_bounded_and_failures_do_not_crash_worker():
    calls = []

    async def cleanup():
        calls.append(True)
        raise RuntimeError("private database failure")

    worker = EscalationAutomationWorker(FakeLister(), None, FakeLister(), None, cleanup=cleanup)
    for _ in range(21):
        await worker.cycle()
    assert len(calls) == 3


@pytest.mark.anyio
async def test_repeated_human_request_does_not_schedule_another_immediate_triage():
    class RecordedGateway(ApiCustomerChatGateway):
        async def request_human_support(self, *args):
            result = await super().request_human_support(*args)
            return result.model_copy(update={"is_new_request": False})

    gateway = RecordedGateway()
    configure_dependencies(gateway)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            CONVERSATION_PATH + "/human-request", headers={"X-SupportPilot-Session": CUSTOMER_TOKEN}
        )
    assert response.status_code == 200
    assert gateway.background_triage_calls == []


@pytest.mark.anyio
async def test_bounded_synthetic_api_429_smoke_and_fresh_test_window():
    class SmokeGateway(ApiCustomerChatGateway):
        count = 0

        async def create_session(self, *args):
            if self.count >= 30:
                raise CustomerChatGatewayError("create_customer_chat_session", "PT429", 12)
            self.count += 1
            return await super().create_session(*args)

    # Deliberate test gateway, not a second production limiter or a live database journey.
    gateway = SmokeGateway()
    configure_dependencies(gateway)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for _ in range(30):
            assert (await client.post(SESSION_PATH)).status_code == 200
        throttled = await client.post(SESSION_PATH)
        assert throttled.status_code == 429
        assert throttled.headers["Retry-After"] == "12"
        assert throttled.json()["error"]["code"] == "rate_limited"
        gateway.count = 0  # Safe fresh test window; never touches real counters/subjects.
        assert (await client.post(SESSION_PATH)).status_code == 200


@pytest.mark.anyio
@pytest.mark.parametrize("marker", [None, "false", 0, [], {}])
async def test_human_orchestration_flag_must_be_present_and_strict_boolean(marker):
    payload = {
        "conversation_id": str(CONVERSATION_ID),
        "status": "human_requested",
        "human_requested_at": datetime.now(UTC).isoformat(),
        "escalation_id": "a0000000-0000-4000-8000-000000000001",
        "triage_status": "pending",
    }
    if marker is not None:
        payload["is_new_request"] = marker
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[payload]))
    ) as client:
        gateway = SupabaseCustomerChatGateway(
            "https://example.test", "synthetic-server-key", client
        )
        with pytest.raises(CustomerChatGatewayError):
            await gateway.request_human_support(CONVERSATION_ID, "a" * 64)
