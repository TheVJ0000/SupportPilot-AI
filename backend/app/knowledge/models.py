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


@dataclass(frozen=True)
class IndexingChunk:
    chunk_id: UUID
    chunk_index: int
    content: str
    content_sha256: str


@dataclass(frozen=True)
class IndexingSource:
    source_id: UUID
    workspace_id: UUID
    title: str
    chunks: list[IndexingChunk]


@dataclass(frozen=True)
class IndexedChunk:
    chunk_index: int
    content_sha256: str
    embedding: list[float]

    def as_rpc_payload(self) -> dict[str, Any]:
        return {
            "chunk_index": self.chunk_index,
            "content_sha256": self.content_sha256,
            "embedding": self.embedding,
        }


class IndexingResult(BaseModel):
    source_id: UUID
    status: Literal["ready"] = "ready"
    chunk_count: int
    embedding_provider: str
    embedding_model: str
    embedding_dimension: Literal[768] = 768
