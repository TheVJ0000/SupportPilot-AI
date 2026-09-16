import asyncio
from uuid import UUID

import pytest

from app.core.config import Settings
from app.escalations.automation import EscalationAutomationWorker, automation_context


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeLister:
    def __init__(self, count=15, error=None):
        self.ids = [UUID(int=i + 1) for i in range(count)]
        self.calls = []
        self.error = error

    async def list_recoverable(self, limit):
        self.calls.append(limit)
        if self.error:
            raise self.error
        return self.ids + self.ids


@pytest.mark.anyio
async def test_bounded_items_concurrency_and_triage_before_delivery():
    gateway = FakeLister()
    active, peak = 0, 0
    events = []

    async def triage(item):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        events.append(("triage", item))
        active -= 1

    async def deliver(item):
        events.append(("delivery", item))

    await EscalationAutomationWorker(gateway, triage, gateway, deliver).cycle()
    assert gateway.calls == [10, 10] and peak == 2
    assert len(events) == 20
    assert [kind for kind, _ in events] == ["triage"] * 10 + ["delivery"] * 10


@pytest.mark.anyio
async def test_missing_providers_do_not_list_or_consume_attempts():
    gateway = FakeLister()
    await EscalationAutomationWorker(gateway, None, gateway, None).cycle()
    assert gateway.calls == []


@pytest.mark.anyio
async def test_immediate_cycle_interval_failure_recovery_and_cancellation():
    gateway = FakeLister(1)
    events, sleeps = [], []

    async def operation(item):
        events.append(item)
        if len(events) == 1:
            raise RuntimeError("private provider data")

    async def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise asyncio.CancelledError()

    worker = EscalationAutomationWorker(gateway, operation, gateway, None, sleep=sleep)
    with pytest.raises(asyncio.CancelledError):
        await worker.run()
    assert len(events) == 2 and sleeps == [60, 60]


@pytest.mark.anyio
async def test_failed_listing_does_not_block_independent_outbox():
    broken, healthy = FakeLister(error=RuntimeError("secret")), FakeLister(1)
    events = []

    async def operation(item):
        events.append(item)

    await EscalationAutomationWorker(broken, operation, healthy, operation).cycle()
    assert len(events) == 1


@pytest.mark.anyio
async def test_two_workers_rely_on_atomic_claim_not_listing():
    gateway, claimed, complete = FakeLister(1), set(), []
    lock = asyncio.Lock()

    async def operation(item):
        async with lock:
            if item in claimed:
                return
            claimed.add(item)
        await asyncio.sleep(0)
        complete.append(item)

    worker = EscalationAutomationWorker(gateway, operation, gateway, None)
    await asyncio.gather(worker.cycle(), worker.cycle())
    assert len(complete) == 1


@pytest.mark.anyio
async def test_lifecycle_missing_supabase_does_not_construct_clients(monkeypatch):
    def unexpected(**_):
        raise AssertionError("Client should not be created")

    monkeypatch.setattr("app.escalations.automation.httpx.AsyncClient", unexpected)
    async with automation_context(
        Settings(_env_file=None, supabase_url=None, supabase_secret_key=None)
    ):
        pass


@pytest.mark.anyio
async def test_lifecycle_runs_immediately_cancels_and_closes(monkeypatch):
    started, stopped = asyncio.Event(), asyncio.Event()

    class FakeClient:
        closed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            self.closed = True

    client = FakeClient()

    async def run(self):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr("app.escalations.automation.httpx.AsyncClient", lambda **_: client)
    monkeypatch.setattr("app.escalations.automation.EscalationAutomationWorker.run", run)
    monkeypatch.setattr("app.escalations.automation.create_triage_agent", lambda _: None)
    settings = Settings(
        _env_file=None,
        supabase_url="https://project.example.test",
        supabase_secret_key="synthetic-key",
    )
    async with automation_context(settings):
        await started.wait()
    assert stopped.is_set() and client.closed
