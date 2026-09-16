import pytest
from pydantic import ValidationError

from app.ai.triage.models import TriageMessage
from app.escalations.context import build_triage_context


def message(content):
    return TriageMessage(role="customer", content=content)


def test_newest_twenty_messages_preserve_chronology():
    messages = [message(str(index)) for index in range(30)]
    context = build_triage_context("human_requested", messages)
    assert [m.content for m in context.conversation] == [str(index) for index in range(10, 30)]


def test_character_budget_discards_older_messages_never_truncates_newest():
    messages = [message(str(index) * 2000) for index in range(9)]
    context = build_triage_context("human_requested", messages)
    assert [m.content for m in context.conversation] == [str(index) * 2000 for index in range(3, 9)]
    assert sum(len(m.content) for m in context.conversation) == 12000


def test_recent_long_assistant_is_preserved_whole():
    messages = [
        message("older"),
        TriageMessage(role="assistant", content="x" * 4000, answer_status="answered"),
    ]
    assert build_triage_context("human_requested", messages).conversation[-1].content == "x" * 4000


@pytest.mark.parametrize(
    "messages",
    [
        [],
        [{"role": "system", "content": "hidden"}],
        [{"role": "customer", "content": "valid", "session_token": "synthetic"}],
        [{"role": "customer", "content": "valid", "citations": []}],
        [{"role": "customer", "content": "valid", "embedding": [1]}],
        [{"role": "customer", "content": "valid", "jwt": "synthetic"}],
        [{"role": "customer", "content": " \n "}],
    ],
)
def test_empty_malformed_or_secret_metadata_fails_safely(messages):
    with pytest.raises((ValueError, ValidationError)):
        build_triage_context("human_requested", messages)
