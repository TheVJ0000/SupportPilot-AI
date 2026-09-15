from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class EmbeddingDocument:
    text: str
    title: str | None = None


class EmbeddingProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    async def embed_documents(self, documents: list[EmbeddingDocument]) -> list[list[float]]: ...
