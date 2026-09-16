import asyncio
import json
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.notifications.gateway import (
    ALLOWED_NOTIFICATION_RPCS,
    NotificationGatewayError,
    SupabaseNotificationGateway,
)
from app.notifications.models import EscalationNotification, NotificationError
from app.notifications.resend import ResendEscalationNotifier, create_notifier
from app.notifications.service import NotificationService

ID = UUID("a0000000-0000-4000-8000-000000000001")


@pytest.fixture
def anyio_backend():
    return "asyncio"


def notification():
    return EscalationNotification(
        notification_id=ID,
        workspace_name="Demo Workspace",
        category="billing",
        priority="high",
        recipient_emails=["admin@example.test", "owner@example.test"],
        attempt_number=1,
    )


@pytest.mark.anyio
async def test_resend_minimal_copy_headers_managers_only_and_secret_safety(caplog):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"id": "provider-message-1"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        notifier = ResendEscalationNotifier(
            SecretStr("synthetic-not-real-key"), "support@example.test", client
        )
        assert await notifier.send(notification()) == "provider-message-1"
        assert "synthetic-not-real-key" not in repr(notifier)
    request = requests[0]
    assert str(request.url) == "https://api.resend.com/emails"
    assert request.headers["Authorization"] == "Bearer synthetic-not-real-key"
    assert request.headers["User-Agent"] == "SupportPilot-AI/0.1"
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["Idempotency-Key"] == f"supportpilot-escalation/{ID}"
    payload = json.loads(request.content)
    assert payload == {
        "from": "support@example.test",
        "to": ["admin@example.test"],
        "bcc": ["owner@example.test"],
        "subject": "[SupportPilot] High priority support escalation",
        "text": (
            "SupportPilot recorded a support escalation for Demo Workspace.\n\n"
            "Category: Billing\nPriority: High\n\n"
            "Sign in to SupportPilot to review the conversation and escalation."
        ),
    }
    assert "synthetic-not-real-key" not in caplog.text
    assert "owner@example.test" not in repr(notification())


@pytest.mark.anyio
@pytest.mark.parametrize(
    "status,code,count",
    [
        (429, "notification_rate_limited", 3),
        (500, "notification_delivery_unknown", 3),
        (408, "notification_delivery_unknown", 3),
        (401, "notification_auth_failed", 1),
        (403, "notification_auth_failed", 1),
        (422, "notification_configuration_invalid", 1),
        (400, "notification_configuration_invalid", 1),
        (409, "notification_delivery_unknown", 1),
        (302, "notification_configuration_invalid", 1),
    ],
)
async def test_safe_error_mapping_bounded_retries(status, code, count):
    requests, sleeps = [], []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            status, json={"message": "private synthetic credential and recipient"}
        )

    async def sleep(seconds):
        sleeps.append(seconds)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        notifier = ResendEscalationNotifier(
            SecretStr("synthetic-key"), "support@example.test", client, sleep=sleep
        )
        with pytest.raises(NotificationError) as caught:
            await notifier.send(notification())
    assert caught.value.code == code and "private" not in str(caught.value)
    assert len(requests) == count
    assert sleeps == ([0.25, 0.5] if count == 3 else [])
    assert len({request.headers["Idempotency-Key"] for request in requests}) == 1
    assert len({request.content for request in requests}) == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    "error,code",
    [
        (httpx.ReadTimeout, "notification_delivery_unknown"),
        (httpx.WriteError, "notification_delivery_unknown"),
        (httpx.ConnectError, "notification_provider_unavailable"),
    ],
)
async def test_network_ambiguity_excluded_from_long_retry(error, code):
    calls = []

    async def sleep(_):
        pass

    def handler(request):
        calls.append(request)
        raise error("private token", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(NotificationError) as caught:
            await ResendEscalationNotifier(
                SecretStr("key"), "support@example.test", client, sleep=sleep
            ).send(notification())
    assert caught.value.code == code and len(calls) == 3 and "token" not in str(caught.value)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "payload", [{}, {"id": ""}, {"id": "x" * 201}, {"id": 123}, {"id": " bad "}]
)
async def test_invalid_success_is_ambiguous(payload):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as client:
        with pytest.raises(NotificationError) as caught:
            await ResendEscalationNotifier(SecretStr("key"), "support@example.test", client).send(
                notification()
            )
    assert caught.value.code == "notification_delivery_unknown"


def test_optional_configuration_and_strict_minimal_context():
    settings = Settings(
        _env_file=None, resend_api_key="synthetic-key", resend_from_email="bad\naddress"
    )
    assert "synthetic-key" not in repr(settings)
    assert create_notifier(settings, object()) is None
    assert create_notifier(Settings(_env_file=None, resend_api_key=None), object()) is None
    with pytest.raises(ValidationError):
        EscalationNotification.model_validate(
            notification().model_dump() | {"summary": "customer transcript"}
        )
    with pytest.raises(ValidationError):
        EscalationNotification.model_validate(
            notification().model_dump() | {"recipient_emails": ["bad\naddress"]}
        )


class FakeGateway:
    def __init__(self, begun=True):
        self.calls = []
        self.begun = begun

    async def begin(self, notification_id):
        self.calls.append(("begin", notification_id))
        return notification() if self.begun else None

    async def complete(self, *args):
        self.calls.append(("complete", *args))

    async def fail(self, *args):
        self.calls.append(("fail", *args))


class FakeNotifier:
    provider_name = "resend"

    def __init__(self, error=None):
        self.error = error
        self.calls = []

    async def send(self, value):
        self.calls.append(value)
        if self.error:
            raise self.error
        return "message-1"


@pytest.mark.anyio
async def test_delivery_missing_config_skips_and_sent_begin_skips():
    gateway = FakeGateway()
    await NotificationService(gateway, None).deliver(ID)
    assert gateway.calls == []
    notifier = FakeNotifier()
    await NotificationService(FakeGateway(False), notifier).deliver(ID)
    assert notifier.calls == []


@pytest.mark.anyio
async def test_delivery_success_completion_and_independent_failure():
    gateway = FakeGateway()
    await NotificationService(gateway, FakeNotifier()).deliver(ID)
    assert gateway.calls[-1] == ("complete", notification(), "resend", "message-1")
    gateway = FakeGateway()
    await NotificationService(
        gateway, FakeNotifier(NotificationError("notification_auth_failed"))
    ).deliver(ID)
    assert gateway.calls[-1] == ("fail", notification(), "notification_auth_failed")


@pytest.mark.anyio
async def test_delivery_cancel_records_ambiguity_and_propagates():
    gateway = FakeGateway()
    with pytest.raises(asyncio.CancelledError):
        await NotificationService(gateway, FakeNotifier(asyncio.CancelledError())).deliver(ID)
    assert gateway.calls[-1] == ("fail", notification(), "notification_delivery_unknown")


@pytest.mark.anyio
async def test_notification_gateway_fixed_rpcs_attempt_fencing_and_ids():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("list_recoverable_escalation_notifications"):
            return httpx.Response(200, json=[str(ID)])
        if request.url.path.endswith("begin_escalation_notification"):
            return httpx.Response(200, json=notification().model_dump(mode="json"))
        return httpx.Response(200, json=True)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabaseNotificationGateway(
            "https://project.example.test", "synthetic-key", client
        )
        assert await gateway.list_recoverable(10) == [ID]
        result = await gateway.begin(ID)
        await gateway.complete(result, "resend", "message-1")
        await gateway.fail(result, "notification_failed")
        with pytest.raises(NotificationGatewayError):
            await gateway._rpc("query_database", {})
    assert len(requests) == len(ALLOWED_NOTIFICATION_RPCS) == 4
    assert json.loads(requests[2].content)["expected_attempt_number"] == 1
    assert json.loads(requests[3].content)["expected_attempt_number"] == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        notification().model_dump(mode="json") | {"notification_id": str(UUID(int=2))},
        notification().model_dump(mode="json") | {"session_token": "private"},
    ],
)
async def test_notification_gateway_rejects_extra_or_wrong_context(payload):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as client:
        with pytest.raises(NotificationGatewayError):
            await SupabaseNotificationGateway("https://project.example.test", "key", client).begin(
                ID
            )
