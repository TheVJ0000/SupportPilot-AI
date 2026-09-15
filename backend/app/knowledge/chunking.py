import hashlib
import re
from dataclasses import dataclass

from app.knowledge.errors import ExtractionError
from app.knowledge.models import ExtractionSegment, KnowledgeChunk, Locator

TARGET_CHUNK_CHARS = 1_400
MAX_CHUNK_CHARS = 2_000
DATABASE_MAX_CHUNK_CHARS = 2_200
OVERLAP_CHARS = 180
MAX_CHUNKS_PER_SOURCE = 1_000

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class _Piece:
    text: str
    locator: Locator


def _hard_split(text: str, limit: int) -> list[str]:
    pieces = []
    remaining = text.strip()
    while len(remaining) > limit:
        split_at = remaining.rfind(" ", 0, limit + 1)
        if split_at < limit // 2:
            split_at = limit
        pieces.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        pieces.append(remaining)
    return pieces


def _split_oversized_block(text: str) -> list[str]:
    sentences = _SENTENCE_BOUNDARY.split(text.strip())
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        for candidate in _hard_split(sentence, MAX_CHUNK_CHARS):
            combined = f"{current} {candidate}".strip()
            if current and len(combined) > MAX_CHUNK_CHARS:
                pieces.append(current)
                current = candidate
            else:
                current = combined
    if current:
        pieces.append(current)
    return pieces


def _pieces_from_segments(segments: list[ExtractionSegment]) -> list[_Piece]:
    pieces = []
    for segment in segments:
        for block in segment.text.split("\n\n"):
            normalized_block = block.strip()
            if not normalized_block:
                continue
            block_pieces = (
                [normalized_block]
                if len(normalized_block) <= MAX_CHUNK_CHARS
                else _split_oversized_block(normalized_block)
            )
            pieces.extend(_Piece(text=piece, locator=segment.locator) for piece in block_pieces)
    return pieces


def _aggregate_locator(locators: list[Locator]) -> Locator:
    kind = str(locators[0]["kind"])
    if any(locator.get("kind") != kind for locator in locators):
        raise ExtractionError("chunking_failed")
    if kind == "faq":
        return {"kind": "faq"}

    range_fields = {
        "pdf": ("page_start", "page_end"),
        "docx": ("block_start", "block_end"),
        "text": ("line_start", "line_end"),
        "markdown": ("line_start", "line_end"),
    }
    try:
        start_field, end_field = range_fields[kind]
        return {
            "kind": kind,
            start_field: min(int(locator[start_field]) for locator in locators),
            end_field: max(int(locator[end_field]) for locator in locators),
        }
    except (KeyError, TypeError, ValueError) as error:
        raise ExtractionError("chunking_failed") from error


def _overlap_piece(content: str, locator: Locator) -> _Piece | None:
    if len(content) <= OVERLAP_CHARS:
        return None
    overlap = content[-OVERLAP_CHARS:]
    first_space = overlap.find(" ")
    if first_space >= 0:
        overlap = overlap[first_space + 1 :]
    overlap = overlap.strip()
    return _Piece(text=overlap, locator=locator) if overlap else None


def chunk_segments(segments: list[ExtractionSegment]) -> list[KnowledgeChunk]:
    pieces = _pieces_from_segments(segments)
    if not pieces:
        raise ExtractionError("no_extractable_text")

    groups: list[list[_Piece]] = []
    current: list[_Piece] = []
    current_length = 0
    for piece in pieces:
        separator_length = 2 if current else 0
        if current and current_length + separator_length + len(piece.text) > TARGET_CHUNK_CHARS:
            groups.append(current)
            rendered = "\n\n".join(item.text for item in current)
            locator = _aggregate_locator([item.locator for item in current])
            overlap = _overlap_piece(rendered, locator)
            current = (
                [overlap]
                if overlap and len(overlap.text) + 2 + len(piece.text) <= MAX_CHUNK_CHARS
                else []
            )
            current_length = len(current[0].text) if current else 0
            separator_length = 2 if current else 0

        if current_length + separator_length + len(piece.text) > MAX_CHUNK_CHARS:
            if current:
                groups.append(current)
            current = [piece]
            current_length = len(piece.text)
        else:
            current.append(piece)
            current_length += separator_length + len(piece.text)

    if current:
        groups.append(current)
    if len(groups) > MAX_CHUNKS_PER_SOURCE:
        raise ExtractionError("chunking_failed")

    chunks = []
    for index, group in enumerate(groups):
        content = "\n\n".join(piece.text for piece in group).strip()
        if not content or len(content) > MAX_CHUNK_CHARS:
            raise ExtractionError("chunking_failed")
        chunks.append(
            KnowledgeChunk(
                chunk_index=index,
                content=content,
                content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                char_count=len(content),
                locator=_aggregate_locator([piece.locator for piece in group]),
            )
        )
    return chunks
