from app.ai.triage.models import TriageContext, TriageMessage

MAX_TRIAGE_MESSAGES = 20
MAX_TRIAGE_CONTEXT_CHARS = 12000


def build_triage_context(trigger_reason: str, messages: list[TriageMessage]) -> TriageContext:
    """Keep newest persisted messages whole, then restore chronological order."""
    selected: list[TriageMessage] = []
    remaining = MAX_TRIAGE_CONTEXT_CHARS
    for message in reversed(messages[-MAX_TRIAGE_MESSAGES:]):
        validated = TriageMessage.model_validate(message)
        if len(validated.content) > remaining:
            break
        selected.append(validated)
        remaining -= len(validated.content)
    return TriageContext(trigger_reason=trigger_reason, conversation=list(reversed(selected)))
