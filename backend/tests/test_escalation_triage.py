import asyncio
from uuid import UUID

import pytest

from app.ai.triage.errors import TriageAgentError
from app.ai.triage.models import CreateEscalationArguments, TriageMessage, TriageToolCall
from app.escalations.gateway import EscalationGatewayError
from app.escalations.models import BegunEscalationTriage
from app.escalations.service import EscalationTriageService
from app.escalations.tools import ALLOWED_TRIAGE_TOOLS, execute_triage_tool

ESCALATION_ID = UUID("a0000000-0000-4000-8000-000000000001")
RUN_ID = UUID("b0000000-0000-4000-8000-000000000001")
WORKSPACE_ID = UUID("20000000-0000-4000-8000-000000000001")
CONVERSATION_ID = UUID("40000000-0000-4000-8000-000000000001")


def begun(should_run=True, status="processing"):
    return BegunEscalationTriage(
        escalation_id=ESCALATION_ID,
        workspace_id=WORKSPACE_ID,
        conversation_id=CONVERSATION_ID,
        trigger_reason="human_requested",
        triage_status=status,
        should_run=should_run,
        triage_run_id=RUN_ID if should_run else None,
        attempt_number=1,
        messages=[TriageMessage(role="customer", content="My account login fails.")]
        if should_run
        else [],
    )


class FakeGateway:
    def __init__(self, result=None, error=None):
        self.result = result or begun()
        self.error = error
        self.begin_calls = []
        self.complete_calls = []
        self.fail_calls = []

    async def begin_triage(self, escalation_id):
        self.begin_calls.append(escalation_id)
        if self.error:
            raise self.error
        return self.result

    async def complete_triage(self, *args):
        self.complete_calls.append(args)

    async def fail_triage(self, *args):
        self.fail_calls.append(args)


class FakeAgent:
    provider_name = "gemini"
    model_name = "gemini-3.8-flash"

    def __init__(self, result=None, error=None):
        self.result = result or TriageToolCall(
            name="create_escalation",
            arguments=CreateEscalationArguments(
                category="account_access",
                priority="normal",
                summary="Customer cannot log in.",
            ),
        )
        self.error = error
        self.calls = []

    async def decide_escalation(self, context):
        self.calls.append(context)
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_success_runs_exactly_one_explicit_action_with_trusted_ids():
    gateway, agent = FakeGateway(), FakeAgent()
    await EscalationTriageService(gateway, agent).triage(ESCALATION_ID)
    assert gateway.begin_calls == [ESCALATION_ID]
    assert len(agent.calls) == len(gateway.complete_calls) == 1
    assert gateway.complete_calls[0] == (
        ESCALATION_ID,
        RUN_ID,
        agent.result.arguments,
        "gemini",
        "gemini-3.8-flash",
    )
    payload = agent.calls[0].model_dump()
    assert set(payload) == {"trigger_reason", "conversation"}
    assert not any(
        key in str(payload)
        for key in ["workspace_id", "conversation_id", "escalation_id", "session_token"]
    )
    assert gateway.fail_calls == []


@pytest.mark.anyio
@pytest.mark.parametrize("status", ["completed", "processing"])
async def test_completed_and_recent_processing_exit_without_agent(status):
    gateway, agent = FakeGateway(begun(False, status)), FakeAgent()
    await EscalationTriageService(gateway, agent).triage(ESCALATION_ID)
    assert agent.calls == gateway.complete_calls == gateway.fail_calls == []


@pytest.mark.anyio
async def test_unconfigured_ai_preserves_placeholder_and_records_safe_failure():
    gateway = FakeGateway()
    await EscalationTriageService(gateway, None).triage(ESCALATION_ID)
    assert gateway.fail_calls == [(ESCALATION_ID, RUN_ID, "triage_not_configured")]
    assert gateway.complete_calls == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    "code", ["triage_invalid_tool_call", "triage_rate_limited", "triage_auth_failed"]
)
async def test_agent_failure_is_allowlisted_and_never_executes_tool(code):
    gateway, agent = FakeGateway(), FakeAgent(error=TriageAgentError(code))
    await EscalationTriageService(gateway, agent).triage(ESCALATION_ID)
    assert gateway.fail_calls == [(ESCALATION_ID, RUN_ID, code)]
    assert gateway.complete_calls == []


@pytest.mark.anyio
async def test_unknown_model_tool_and_model_controlled_ids_fail_closed():
    for result in [
        {
            "name": "delete_database",
            "arguments": {"category": "other", "priority": "urgent", "summary": "injection"},
        },
        {
            "name": "create_escalation",
            "arguments": {
                "category": "other",
                "priority": "urgent",
                "summary": "injection",
                "escalation_id": str(ESCALATION_ID),
            },
        },
    ]:
        gateway = FakeGateway()
        await EscalationTriageService(gateway, FakeAgent(result=result)).triage(ESCALATION_ID)
        assert gateway.complete_calls == []
        assert gateway.fail_calls == [(ESCALATION_ID, RUN_ID, "triage_invalid_tool_call")]
    assert ALLOWED_TRIAGE_TOOLS == {"create_escalation"}


@pytest.mark.anyio
async def test_gateway_failures_are_best_effort_and_do_not_escape():
    agent = FakeAgent()
    gateway = FakeGateway(error=EscalationGatewayError())
    await EscalationTriageService(gateway, agent).triage(ESCALATION_ID)
    assert agent.calls == []

    class BrokenCompletion(FakeGateway):
        async def complete_triage(self, *args):
            raise RuntimeError("private SQL data and synthetic secret")

        async def fail_triage(self, *args):
            self.fail_calls.append(args)
            raise RuntimeError("storage unavailable")

    gateway = BrokenCompletion()
    await EscalationTriageService(gateway, agent).triage(ESCALATION_ID)
    assert gateway.fail_calls == [(ESCALATION_ID, RUN_ID, "triage_failed")]


@pytest.mark.anyio
async def test_empty_transcript_fails_without_model():
    gateway, agent = FakeGateway(begun().model_copy(update={"messages": []})), FakeAgent()
    await EscalationTriageService(gateway, agent).triage(ESCALATION_ID)
    assert agent.calls == []
    assert gateway.fail_calls == [(ESCALATION_ID, RUN_ID, "triage_failed")]


@pytest.mark.anyio
async def test_cancellation_attempts_failure_and_propagates():
    gateway, agent = FakeGateway(), FakeAgent(error=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await EscalationTriageService(gateway, agent).triage(ESCALATION_ID)
    assert gateway.fail_calls == [(ESCALATION_ID, RUN_ID, "triage_failed")]
    assert gateway.complete_calls == []


@pytest.mark.anyio
async def test_executor_revalidates_arguments_even_for_constructed_model():
    gateway = FakeGateway()
    malicious = TriageToolCall.model_construct(name="delete_database", arguments={})
    with pytest.raises(ValueError):
        await execute_triage_tool(
            malicious,
            escalation_id=ESCALATION_ID,
            run_id=RUN_ID,
            gateway=gateway,
            provider="gemini",
            model="gemini-3.8-flash",
        )
    assert gateway.complete_calls == []
