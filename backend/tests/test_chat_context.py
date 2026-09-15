from dataclasses import dataclass

from app.chat.context import MAX_CONTEXT_MESSAGES, build_contextual_question
from app.rag.service import MAX_QUERY_CHARS


@dataclass(frozen=True)
class Message:
    role: str
    content: str


def test_no_history_returns_current_question_unchanged() -> None:
    current = "What is your refund policy?"

    assert build_contextual_question(current, []) == current


def test_simple_follow_up_includes_exchange_and_full_current_question() -> None:
    result = build_contextual_question(
        "What about after that?",
        [
            Message("customer", "What is your refund policy?"),
            Message("assistant", "The policy covers purchases within 30 days."),
        ],
    )

    assert result == (
        "Previous customer: What is your refund policy?\n"
        "Previous assistant: The policy covers purchases within 30 days.\n"
        "Current customer question: What about after that?"
    )


def test_only_six_immediately_preceding_messages_are_eligible() -> None:
    history = [Message("customer", f"message-{index}") for index in range(8)]

    result = build_contextual_question("current", history)

    assert result.count("Previous customer:") == MAX_CONTEXT_MESSAGES
    assert "message-1" not in result
    assert "message-2" in result
    assert result.index("message-2") < result.index("message-7")


def test_length_bound_drops_older_context_first_and_preserves_order() -> None:
    history = [
        Message("customer", "x" * 1970),
        Message("assistant", "newer answer"),
    ]

    result = build_contextual_question("What about that?", history)

    assert len(result) <= MAX_QUERY_CHARS
    assert "x" * 100 not in result
    assert result.startswith("Previous assistant: newer answer")
    assert result.endswith("Current customer question: What about that?")


def test_near_limit_current_question_is_never_truncated_for_history() -> None:
    current = "q" * (MAX_QUERY_CHARS - 1)

    result = build_contextual_question(current, [Message("assistant", "prior")])

    assert result == current
    assert len(result) == MAX_QUERY_CHARS - 1
