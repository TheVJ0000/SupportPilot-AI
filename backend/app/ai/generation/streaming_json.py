import json
import string
from dataclasses import dataclass

from pydantic import ValidationError

from app.ai.generation.models import (
    MAX_GENERATED_ANSWER_CHARS,
    GenerationAnswerDelta,
    GenerationDecisionEvent,
)


class IncrementalGenerationJsonError(ValueError):
    """The provider stream no longer matches the exact grounded-output schema."""


@dataclass(frozen=True)
class ParsedGenerationJson:
    raw_json: str
    prefix: GenerationDecisionEvent
    answer: str


_NEED_MORE = object()
_HEX_DIGITS = frozenset(string.hexdigits)
_SIMPLE_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}


class GroundedGenerationJsonStreamParser:
    """Incrementally parses only decision/evidence_ids/answer structured JSON."""

    def __init__(self) -> None:
        self._buffer = ""
        self._raw_parts: list[str] = []
        self._position = 0
        self._state = "object_start"
        self._decision: str | None = None
        self._evidence_ids: list[str] | None = None
        self._prefix: GenerationDecisionEvent | None = None
        self._answer_parts: list[str] = []
        self._answer_length = 0
        self._answer_started = False
        self._answer_mode = "normal"
        self._unicode_digits = ""
        self._unicode_completes_surrogate = False
        self._pending_high_surrogate: int | None = None

    @property
    def prefix(self) -> GenerationDecisionEvent | None:
        return self._prefix

    @property
    def answer(self) -> str:
        return "".join(self._answer_parts)

    def _skip_whitespace(self) -> None:
        while self._position < len(self._buffer) and self._buffer[self._position] in " \t\r\n":
            self._position += 1

    def _expect_character(self, expected: str) -> bool:
        self._skip_whitespace()
        if self._position >= len(self._buffer):
            return False
        if self._buffer[self._position] != expected:
            raise IncrementalGenerationJsonError("Unexpected structured-output token")
        self._position += 1
        return True

    def _json_string_token(self) -> str | object:
        self._skip_whitespace()
        if self._position >= len(self._buffer):
            return _NEED_MORE
        if self._buffer[self._position] != '"':
            raise IncrementalGenerationJsonError("Expected a JSON string")
        index = self._position + 1
        escaped = False
        while index < len(self._buffer):
            character = self._buffer[index]
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                token = self._buffer[self._position : index + 1]
                try:
                    value = json.loads(token)
                except (TypeError, json.JSONDecodeError):
                    raise IncrementalGenerationJsonError("Invalid JSON string") from None
                if not isinstance(value, str):
                    raise IncrementalGenerationJsonError("Expected a JSON string")
                self._position = index + 1
                return value
            elif ord(character) < 0x20:
                raise IncrementalGenerationJsonError("Unescaped JSON control character")
            index += 1
        return _NEED_MORE

    def _json_array_token(self) -> list[object] | object:
        self._skip_whitespace()
        if self._position >= len(self._buffer):
            return _NEED_MORE
        if self._buffer[self._position] != "[":
            raise IncrementalGenerationJsonError("Expected a JSON array")
        index = self._position
        depth = 0
        in_string = False
        escaped = False
        while index < len(self._buffer):
            character = self._buffer[index]
            if in_string:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    in_string = False
                elif ord(character) < 0x20:
                    raise IncrementalGenerationJsonError("Unescaped JSON control character")
            elif character == '"':
                in_string = True
            elif character == "[":
                depth += 1
            elif character == "]":
                depth -= 1
                if depth == 0:
                    token = self._buffer[self._position : index + 1]
                    try:
                        value = json.loads(token)
                    except (TypeError, json.JSONDecodeError):
                        raise IncrementalGenerationJsonError("Invalid JSON array") from None
                    if not isinstance(value, list):
                        raise IncrementalGenerationJsonError("Expected a JSON array")
                    self._position = index + 1
                    return value
                if depth < 0:
                    raise IncrementalGenerationJsonError("Invalid JSON array")
            index += 1
        return _NEED_MORE

    def _append_answer_character(self, character: str, delta_parts: list[str]) -> None:
        self._answer_length += len(character)
        if self._answer_length > MAX_GENERATED_ANSWER_CHARS:
            raise IncrementalGenerationJsonError("Generated answer exceeds the safe limit")
        self._answer_parts.append(character)
        if self._decision == "answerable":
            delta_parts.append(character)

    def _consume_answer(self, delta_parts: list[str]) -> bool:
        if not self._answer_started:
            self._skip_whitespace()
            if self._position >= len(self._buffer):
                return False
            if self._buffer[self._position] != '"':
                raise IncrementalGenerationJsonError("Expected the answer JSON string")
            self._position += 1
            self._answer_started = True

        while self._position < len(self._buffer):
            character = self._buffer[self._position]
            self._position += 1
            if self._answer_mode == "unicode":
                if character not in _HEX_DIGITS:
                    raise IncrementalGenerationJsonError("Invalid Unicode escape")
                self._unicode_digits += character
                if len(self._unicode_digits) < 4:
                    continue
                code_point = int(self._unicode_digits, 16)
                self._answer_mode = "normal"
                self._unicode_digits = ""
                if self._unicode_completes_surrogate:
                    if not 0xDC00 <= code_point <= 0xDFFF:
                        raise IncrementalGenerationJsonError("Invalid Unicode surrogate pair")
                    high = self._pending_high_surrogate
                    if high is None:
                        raise IncrementalGenerationJsonError("Invalid Unicode surrogate state")
                    combined = 0x10000 + ((high - 0xD800) << 10) + (code_point - 0xDC00)
                    self._pending_high_surrogate = None
                    self._unicode_completes_surrogate = False
                    self._append_answer_character(chr(combined), delta_parts)
                elif 0xD800 <= code_point <= 0xDBFF:
                    self._pending_high_surrogate = code_point
                elif 0xDC00 <= code_point <= 0xDFFF:
                    raise IncrementalGenerationJsonError("Unexpected low Unicode surrogate")
                else:
                    self._append_answer_character(chr(code_point), delta_parts)
                continue

            if self._answer_mode == "escape":
                if self._pending_high_surrogate is not None and character != "u":
                    raise IncrementalGenerationJsonError("Invalid Unicode surrogate pair")
                if character == "u":
                    self._answer_mode = "unicode"
                    self._unicode_digits = ""
                    self._unicode_completes_surrogate = self._pending_high_surrogate is not None
                    continue
                decoded = _SIMPLE_ESCAPES.get(character)
                if decoded is None:
                    raise IncrementalGenerationJsonError("Invalid JSON escape")
                self._answer_mode = "normal"
                self._append_answer_character(decoded, delta_parts)
                continue

            if self._pending_high_surrogate is not None:
                if character != "\\":
                    raise IncrementalGenerationJsonError("Invalid Unicode surrogate pair")
                self._answer_mode = "escape"
                continue
            if character == '"':
                self._state = "object_end"
                return True
            if character == "\\":
                self._answer_mode = "escape"
                continue
            if ord(character) < 0x20 or 0xD800 <= ord(character) <= 0xDFFF:
                raise IncrementalGenerationJsonError("Invalid JSON answer character")
            self._append_answer_character(character, delta_parts)
        return False

    def feed(self, chunk: str) -> list[GenerationDecisionEvent | GenerationAnswerDelta]:
        if not isinstance(chunk, str):
            raise IncrementalGenerationJsonError("Provider chunks must be text")
        self._buffer += chunk
        self._raw_parts.append(chunk)
        events: list[GenerationDecisionEvent | GenerationAnswerDelta] = []
        delta_parts: list[str] = []

        while True:
            previous_state = self._state
            previous_position = self._position
            if self._state == "object_start":
                if self._expect_character("{"):
                    self._state = "decision_key"
            elif self._state == "decision_key":
                value = self._json_string_token()
                if value is not _NEED_MORE:
                    if value != "decision":
                        raise IncrementalGenerationJsonError("Decision must be the first property")
                    self._state = "decision_colon"
            elif self._state == "decision_colon":
                if self._expect_character(":"):
                    self._state = "decision_value"
            elif self._state == "decision_value":
                value = self._json_string_token()
                if value is not _NEED_MORE:
                    self._decision = value
                    self._state = "decision_separator"
            elif self._state == "decision_separator":
                if self._expect_character(","):
                    self._state = "evidence_key"
            elif self._state == "evidence_key":
                value = self._json_string_token()
                if value is not _NEED_MORE:
                    if value != "evidence_ids":
                        raise IncrementalGenerationJsonError(
                            "Evidence IDs must be the second property"
                        )
                    self._state = "evidence_colon"
            elif self._state == "evidence_colon":
                if self._expect_character(":"):
                    self._state = "evidence_value"
            elif self._state == "evidence_value":
                value = self._json_array_token()
                if value is not _NEED_MORE:
                    self._evidence_ids = value
                    try:
                        self._prefix = GenerationDecisionEvent(
                            decision=self._decision,
                            evidence_ids=self._evidence_ids,
                        )
                    except (TypeError, ValidationError, ValueError):
                        raise IncrementalGenerationJsonError(
                            "Invalid decision or evidence IDs"
                        ) from None
                    events.append(self._prefix)
                    self._state = "evidence_separator"
            elif self._state == "evidence_separator":
                if self._expect_character(","):
                    self._state = "answer_key"
            elif self._state == "answer_key":
                value = self._json_string_token()
                if value is not _NEED_MORE:
                    if value != "answer":
                        raise IncrementalGenerationJsonError("Answer must be the third property")
                    self._state = "answer_colon"
            elif self._state == "answer_colon":
                if self._expect_character(":"):
                    self._state = "answer_value"
            elif self._state == "answer_value":
                self._consume_answer(delta_parts)
            elif self._state == "object_end":
                if self._expect_character("}"):
                    self._state = "done"
            elif self._state == "done":
                self._skip_whitespace()
                if self._position < len(self._buffer):
                    raise IncrementalGenerationJsonError("Unexpected trailing structured output")
                break
            else:
                raise IncrementalGenerationJsonError("Invalid parser state")

            if self._state == previous_state and self._position == previous_position:
                break

        if delta_parts:
            events.append(GenerationAnswerDelta(text="".join(delta_parts)))
        return events

    def finish(self) -> ParsedGenerationJson:
        self.feed("")
        if self._state != "done" or self._prefix is None:
            raise IncrementalGenerationJsonError("Incomplete structured output")
        return ParsedGenerationJson(
            raw_json="".join(self._raw_parts),
            prefix=self._prefix,
            answer=self.answer,
        )
