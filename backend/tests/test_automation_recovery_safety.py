import asyncio

import httpx
import pytest
from pydantic import SecretStr

from app.escalations.automation import EscalationAutomationWorker
from app.escalations.gateway import EscalationGatewayError, SupabaseEscalationGateway
from app.notifications.gateway import NotificationGatewayError, SupabaseNotificationGateway
from app.notifications.resend import ResendEscalationNotifier
from app.notifications.service import NotificationService
from tests.test_escalation_automation import FakeLister
from tests.test_notifications import ID, FakeGateway, FakeNotifier, notification


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_cycle_exception_does_not_kill_future_cycles():
    gateway = FakeLister(0)
    cycles, sleeps = [], []

    class BrokenFirstCycle(EscalationAutomationWorker):
        async def cycle(self):
            cycles.append(True)
            if len(cycles) == 1:
                raise RuntimeError("private provider failure")

    async def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await BrokenFirstCycle(gateway, None, gateway, None, sleep=sleep).run()
    assert len(cycles) == 2 and sleeps == [60, 60]


@pytest.mark.anyio
@pytest.mark.parametrize("first_status", [429, 500, 408])
async def test_successful_immediate_retry_reuses_identical_payload(first_status):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(first_status if len(requests) == 1 else 200, json={"id": "message-1"})

    async def sleep(_):
        pass

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ResendEscalationNotifier(
            SecretStr("key"), "support@example.test", client, sleep=sleep
        ).send(notification())
    assert result == "message-1" and len(requests) == 2
    assert requests[0].headers["Idempotency-Key"] == requests[1].headers["Idempotency-Key"]
    assert requests[0].content == requests[1].content


@pytest.mark.anyio
async def test_completion_failure_records_unknown():
    class BrokenCompletion(FakeGateway):
        async def complete(self, *args):
            raise NotificationGatewayError()

    gateway = BrokenCompletion()
    await NotificationService(gateway, FakeNotifier()).deliver(ID)
    assert gateway.calls[-1] == ("fail", notification(), "notification_delivery_unknown")


@pytest.mark.anyio
async def test_completion_cancellation_propagates_and_attempts_safe_unknown():
    class CanceledCompletion(FakeGateway):
        async def complete(self, *args):
            raise asyncio.CancelledError()

    gateway = CanceledCompletion()
    with pytest.raises(asyncio.CancelledError):
        await NotificationService(gateway, FakeNotifier()).deliver(ID)
    assert gateway.calls[-1] == ("fail", notification(), "notification_delivery_unknown")


@pytest.mark.anyio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="private raw secret"),
        httpx.Response(200, text="malformed private response"),
    ],
)
async def test_notification_gateway_sanitizes_storage_failure(response):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response)) as client:
        with pytest.raises(NotificationGatewayError) as caught:
            await SupabaseNotificationGateway("https://project.example.test", "key", client).begin(
                ID
            )
    assert "private" not in str(caught.value)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "gateway_class,error",
    [
        (SupabaseEscalationGateway, EscalationGatewayError),
        (SupabaseNotificationGateway, NotificationGatewayError),
    ],
)
@pytest.mark.parametrize("payload", [["not-uuid"], {}, [str(ID)] * 11, [123]])
async def test_listing_rejects_invalid_or_oversized_response(gateway_class, error, payload):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as client:
        gateway = gateway_class("https://project.example.test", "key", client)
        with pytest.raises(error):
            await gateway.list_recoverable(10)
        with pytest.raises(error):
            await gateway.list_recoverable(0)


@pytest.mark.anyio
async def test_escalation_recovery_listing_bounded_ids_only():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=[str(ID)])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabaseEscalationGateway("https://project.example.test", "key", client)
        assert await gateway.list_recoverable(10) == [ID]
        with pytest.raises(EscalationGatewayError):
            await gateway.list_recoverable(21)
    assert len(requests) == 1 and requests[0].url.path.endswith("list_recoverable_escalations")
