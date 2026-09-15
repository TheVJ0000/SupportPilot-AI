import hashlib

from app.knowledge.chunking import MAX_CHUNK_CHARS, OVERLAP_CHARS, chunk_segments
from app.knowledge.models import ExtractionSegment
from app.knowledge.normalization import normalize_segments, normalize_text


def segment(text: str, start: int, end: int) -> ExtractionSegment:
    return ExtractionSegment(
        text=text,
        locator={"kind": "text", "line_start": start, "line_end": end},
    )


def test_normalization_is_deterministic_and_removes_unsafe_controls() -> None:
    raw = "Cafe\u0301\r\nline\t with   spaces\x00\n\n\n\nNext"
    expected = "Café\nline with spaces\n\nNext"

    assert normalize_text(raw) == expected
    assert normalize_text(raw) == normalize_text(raw)


def test_normalization_counts_canonical_text_and_removes_empty_segments() -> None:
    normalized, character_count = normalize_segments(
        [segment(" First ", 1, 1), segment("\n ", 2, 2), segment("Second", 3, 3)]
    )

    assert [item.text for item in normalized] == ["First", "Second"]
    assert character_count == len("First\n\nSecond")


def test_small_content_produces_one_hashed_chunk() -> None:
    chunks = chunk_segments([segment("A concise support answer.", 4, 4)])

    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].char_count == len(chunks[0].content)
    assert chunks[0].content_sha256 == hashlib.sha256(chunks[0].content.encode()).hexdigest()
    assert chunks[0].locator == {"kind": "text", "line_start": 4, "line_end": 4}


def test_oversized_paragraph_splits_deterministically_under_the_hard_limit() -> None:
    oversized = " ".join(f"word{index}" for index in range(900))

    first = chunk_segments([segment(oversized, 1, 1)])
    second = chunk_segments([segment(oversized, 1, 1)])

    assert first == second
    assert len(first) > 1
    assert [chunk.chunk_index for chunk in first] == list(range(len(first)))
    assert all(0 < chunk.char_count <= MAX_CHUNK_CHARS for chunk in first)


def test_chunking_preserves_order_adds_modest_overlap_and_aggregates_locators() -> None:
    segments = [
        segment("A" * 900, 1, 10),
        segment("B" * 900, 11, 20),
        segment("C" * 300, 21, 25),
    ]

    chunks = chunk_segments(segments)

    assert chunks[0].content.startswith("A")
    assert chunks[1].content.startswith("A" * OVERLAP_CHARS)
    assert "B" * 100 in chunks[1].content
    assert chunks[1].locator == {"kind": "text", "line_start": 1, "line_end": 25}
    assert chunks[-1].content.endswith("C" * 300)
