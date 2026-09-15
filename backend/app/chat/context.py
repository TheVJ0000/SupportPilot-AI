from collections.abc import Sequence
from typing import Protocol

from app.rag.errors import RetrievalHttpError
from app.rag.service import MAX_QUERY_CHARS, normalize_question

MAX_CONTEXT_MESSAGES = 6


class ContextMessage(Protocol):
    role: str
    content: str


def build_contextual_question(
    current_question: str,
    prior_messages: Sequence[ContextMessage],
) -> str:
    """Build bounded internal RAG input from recent persisted messages."""
    recent_messages = prior_messages[-MAX_CONTEXT_MESSAGES:]
    current_line = f"Current customer question: {current_question}"
    if len(current_line) > MAX_QUERY_CHARS:
        return current_question

    selected_lines: list[str] = []
    for message in reversed(recent_messages):
        label = {
            "customer": "Previous customer",
            "assistant": "Previous assistant",
        }.get(message.role)
        if label is None:
            continue
        try:
            content = normalize_question(message.content, minimum_chars=1)
        except RetrievalHttpError:
            continue
        candidate = f"{label}: {content}"
        contextual_question = "\n".join([candidate, *selected_lines, current_line])
        if len(contextual_question) > MAX_QUERY_CHARS:
            break
        selected_lines.insert(0, candidate)

    if not selected_lines:
        return current_question
    return "\n".join([*selected_lines, current_line])
