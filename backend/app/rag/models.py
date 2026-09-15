from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RetrievalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: UUID
    question: str


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: UUID
    source_id: UUID
    source_title: str
    source_type: Literal["file", "faq"]
    chunk_index: int
    content: str
    locator: dict[str, Any]
    similarity: float


class RetrievalMatch(BaseModel):
    chunk_id: UUID
    source_id: UUID
    source_title: str
    source_type: Literal["file", "faq"]
    chunk_index: int
    content: str
    locator: dict[str, Any]
    similarity: float


class RetrievalResponse(BaseModel):
    workspace_id: UUID
    question: str
    matches: list[RetrievalMatch]
