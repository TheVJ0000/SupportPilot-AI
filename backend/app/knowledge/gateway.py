from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, Protocol
from urllib.parse import quote
from uuid import UUID

import httpx
from fastapi import Depends, HTTPException, status

from app.auth.dependencies import get_authenticated_context
from app.auth.models import AuthenticatedRequestContext
from app.core.config import Settings, get_settings
from app.knowledge.errors import GatewayError
from app.knowledge.extraction import MAX_SOURCE_BYTES
from app.knowledge.models import (
    IndexedChunk,
    IndexingChunk,
    IndexingSource,
    KnowledgeChunk,
    ProcessingSource,
)

KNOWLEDGE_BUCKET = "knowledge-files"
REQUEST_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)


class KnowledgeGateway(Protocol):
    async def begin_extraction(self, source_id: UUID) -> ProcessingSource: ...

    async def download_source(self, storage_path: str) -> bytes: ...

    async def complete_extraction(
        self,
        source_id: UUID,
        chunks: list[KnowledgeChunk],
        extracted_char_count: int,
    ) -> None: ...

    async def fail_extraction(self, source_id: UUID, error_code: str) -> None: ...

    async def begin_indexing(self, source_id: UUID) -> IndexingSource: ...

    async def complete_indexing(
        self,
        source_id: UUID,
        provider_name: str,
        model_name: str,
        dimension: int,
        chunks: list[IndexedChunk],
    ) -> None: ...

    async def fail_indexing(self, source_id: UUID, error_code: str) -> None: ...


class SupabaseKnowledgeGateway:
    """User-scoped access to only the four Supabase operations Phase 3B requires."""

    def __init__(
        self,
        supabase_url: str,
        publishable_key: str,
        access_token: str,
        client: httpx.AsyncClient,
    ) -> None:
        self._base_url = supabase_url.rstrip("/")
        self._client = client
        self._headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "apikey": publishable_key,
        }

    @staticmethod
    def _provider_code(response: httpx.Response) -> str | None:
        try:
            payload = response.json()
        except ValueError:
            return None
        code = payload.get("code") if isinstance(payload, dict) else None
        return code if isinstance(code, str) and len(code) <= 32 else None

    async def _rpc(self, function_name: str, payload: dict[str, Any]) -> Any:
        try:
            response = await self._client.post(
                f"{self._base_url}/rest/v1/rpc/{function_name}",
                headers={**self._headers, "Content-Type": "application/json"},
                json=payload,
            )
        except httpx.RequestError as error:
            raise GatewayError(function_name) from error
        if response.status_code >= 400:
            raise GatewayError(function_name, self._provider_code(response))
        try:
            return response.json()
        except ValueError as error:
            raise GatewayError(function_name) from error

    async def begin_extraction(self, source_id: UUID) -> ProcessingSource:
        payload = await self._rpc(
            "begin_knowledge_extraction", {"target_source_id": str(source_id)}
        )
        row = payload[0] if isinstance(payload, list) and payload else payload
        if not isinstance(row, dict):
            raise GatewayError("begin_knowledge_extraction")
        try:
            result = ProcessingSource(
                source_id=UUID(str(row["source_id"])),
                workspace_id=UUID(str(row["workspace_id"])),
                source_type=row["source_type"],
                storage_path=row.get("storage_path"),
                original_filename=row.get("original_filename"),
                mime_type=row.get("mime_type"),
                byte_size=row.get("byte_size"),
                faq_question=row.get("faq_question"),
                faq_answer=row.get("faq_answer"),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise GatewayError("begin_knowledge_extraction") from error
        optional_text_values = (
            result.storage_path,
            result.original_filename,
            result.mime_type,
            result.faq_question,
            result.faq_answer,
        )
        if (
            result.source_id != source_id
            or result.source_type not in {"file", "faq"}
            or any(
                value is not None and not isinstance(value, str) for value in optional_text_values
            )
            or (result.byte_size is not None and not isinstance(result.byte_size, int))
        ):
            raise GatewayError("begin_knowledge_extraction")
        return result

    async def download_source(self, storage_path: str) -> bytes:
        encoded_path = quote(storage_path, safe="/")
        url = f"{self._base_url}/storage/v1/object/authenticated/{KNOWLEDGE_BUCKET}/{encoded_path}"
        downloaded = bytearray()
        try:
            async with self._client.stream("GET", url, headers=self._headers) as response:
                if response.status_code >= 400:
                    raise GatewayError("download_source", self._provider_code(response))
                async for block in response.aiter_bytes():
                    downloaded.extend(block)
                    if len(downloaded) > MAX_SOURCE_BYTES:
                        raise GatewayError("download_too_large")
        except GatewayError:
            raise
        except httpx.RequestError as error:
            raise GatewayError("download_source") from error
        return bytes(downloaded)

    async def complete_extraction(
        self,
        source_id: UUID,
        chunks: list[KnowledgeChunk],
        extracted_char_count: int,
    ) -> None:
        await self._rpc(
            "complete_knowledge_extraction",
            {
                "target_source_id": str(source_id),
                "chunk_payload": [chunk.as_rpc_payload() for chunk in chunks],
                "total_extracted_char_count": extracted_char_count,
            },
        )

    async def fail_extraction(self, source_id: UUID, error_code: str) -> None:
        await self._rpc(
            "fail_knowledge_extraction",
            {"target_source_id": str(source_id), "error_code": error_code},
        )

    async def begin_indexing(self, source_id: UUID) -> IndexingSource:
        payload = await self._rpc("begin_knowledge_indexing", {"target_source_id": str(source_id)})
        if not isinstance(payload, list) or not payload:
            raise GatewayError("begin_knowledge_indexing")
        chunks: list[IndexingChunk] = []
        try:
            first = payload[0]
            result_source_id = UUID(str(first["source_id"]))
            workspace_id = UUID(str(first["workspace_id"]))
            title = first["title"]
            for expected_index, row in enumerate(payload):
                if (
                    UUID(str(row["source_id"])) != result_source_id
                    or UUID(str(row["workspace_id"])) != workspace_id
                    or row["title"] != title
                    or row["chunk_index"] != expected_index
                ):
                    raise ValueError
                chunks.append(
                    IndexingChunk(
                        chunk_id=UUID(str(row["chunk_id"])),
                        chunk_index=row["chunk_index"],
                        content=row["content"],
                        content_sha256=row["content_sha256"],
                    )
                )
        except (KeyError, TypeError, ValueError) as error:
            raise GatewayError("begin_knowledge_indexing") from error
        if (
            result_source_id != source_id
            or not isinstance(title, str)
            or not 1 <= len(title) <= 200
            or any(
                not chunk.content or len(chunk.content) > 2200 or len(chunk.content_sha256) != 64
                for chunk in chunks
            )
        ):
            raise GatewayError("begin_knowledge_indexing")
        return IndexingSource(result_source_id, workspace_id, title, chunks)

    async def complete_indexing(
        self,
        source_id: UUID,
        provider_name: str,
        model_name: str,
        dimension: int,
        chunks: list[IndexedChunk],
    ) -> None:
        await self._rpc(
            "complete_knowledge_indexing",
            {
                "target_source_id": str(source_id),
                "provider_name": provider_name,
                "model_name": model_name,
                "embedding_dimension": dimension,
                "embedding_payload": [chunk.as_rpc_payload() for chunk in chunks],
            },
        )

    async def fail_indexing(self, source_id: UUID, error_code: str) -> None:
        await self._rpc(
            "fail_knowledge_indexing",
            {"target_source_id": str(source_id), "error_code": error_code},
        )


@asynccontextmanager
async def _gateway_context(
    settings: Settings,
    context: AuthenticatedRequestContext,
) -> AsyncIterator[SupabaseKnowledgeGateway]:
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=False) as client:
        yield SupabaseKnowledgeGateway(
            supabase_url=str(settings.supabase_url),
            publishable_key=settings.supabase_publishable_key or "",
            access_token=context.access_token,
            client=client,
        )


async def get_knowledge_gateway(
    context: Annotated[AuthenticatedRequestContext, Depends(get_authenticated_context)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[KnowledgeGateway]:
    if settings.supabase_url is None or not settings.supabase_publishable_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Knowledge processing is not configured",
        )
    async with _gateway_context(settings, context) as gateway:
        yield gateway
