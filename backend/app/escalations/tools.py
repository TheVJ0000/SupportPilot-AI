from uuid import UUID

from pydantic import TypeAdapter

from app.ai.triage.models import CreateEscalationArguments, ProviderLabel, TriageToolCall
from app.escalations.gateway import EscalationGateway

ALLOWED_TRIAGE_TOOLS = frozenset({"create_escalation"})
_label_adapter = TypeAdapter(ProviderLabel)


async def execute_triage_tool(
    call: TriageToolCall,
    *,
    escalation_id: UUID,
    run_id: UUID,
    gateway: EscalationGateway,
    provider: str,
    model: str,
) -> None:
    """Fixed dispatch: the model provides classification only, never authority or IDs."""
    validated = TriageToolCall.model_validate(call)
    if validated.name not in ALLOWED_TRIAGE_TOOLS:
        raise ValueError("Unknown triage tool")
    arguments = CreateEscalationArguments.model_validate(validated.arguments.model_dump())
    provider = _label_adapter.validate_python(provider)
    model = _label_adapter.validate_python(model)
    await gateway.complete_triage(escalation_id, run_id, arguments, provider, model)
