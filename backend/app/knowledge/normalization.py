import re
import unicodedata

from app.knowledge.errors import ExtractionError
from app.knowledge.models import ExtractionSegment

MAX_NORMALIZED_CHARS = 1_000_000

_HORIZONTAL_WHITESPACE = re.compile(r"[\t \f\v]+")
_EXCESSIVE_NEWLINES = re.compile(r"\n{3,}")


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))
    safe_characters = []
    for character in value:
        if character in {"\n", "\t"}:
            safe_characters.append(character)
            continue
        if unicodedata.category(character) in {"Cc", "Cf"}:
            continue
        safe_characters.append(character)

    normalized_lines = [
        _HORIZONTAL_WHITESPACE.sub(" ", line).strip()
        for line in "".join(safe_characters).split("\n")
    ]
    normalized = "\n".join(normalized_lines).strip()
    return _EXCESSIVE_NEWLINES.sub("\n\n", normalized)


def normalize_segments(segments: list[ExtractionSegment]) -> tuple[list[ExtractionSegment], int]:
    normalized_segments = [
        ExtractionSegment(text=normalized, locator=segment.locator)
        for segment in segments
        if (normalized := normalize_text(segment.text))
    ]
    if not normalized_segments:
        raise ExtractionError("no_extractable_text")

    extracted_char_count = len("\n\n".join(segment.text for segment in normalized_segments))
    if extracted_char_count > MAX_NORMALIZED_CHARS:
        raise ExtractionError("document_too_large")
    return normalized_segments, extracted_char_count
