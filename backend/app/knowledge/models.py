from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

SourceType = Literal["file", "faq"]
Locator = dict[str, Any]


@dataclass(frozen=True)
class ProcessingSource:
    source_id: UUID
    workspace_id: UUID
    source_type: SourceType
    storage_path: str | None
    original_filename: str | None
    mime_type: str | None
    byte_size: int | None
    faq_question: str | None
    faq_answer: str | None


@dataclass(frozen=True)
class ExtractionSegment:
    text: str
    locator: Locator


@dataclass(frozen=True)
class KnowledgeChunk:
    chunk_index: int
    content: str
    content_sha256: str
    char_count: int
    locator: Locator

    def as_rpc_payload(self) -> dict[str, Any]:
        return {
            "chunk_index": self.chunk_index,
            "content": self.content,
            "content_sha256": self.content_sha256,
            "char_count": self.char_count,
            "locator": self.locator,
        }


class ProcessingResult(BaseModel):
    source_id: UUID
    status: Literal["pending"] = "pending"
    chunk_count: int
    extracted_char_count: int
    next_stage: Literal["embedding"] = "embedding"
