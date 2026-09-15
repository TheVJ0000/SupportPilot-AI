import math
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Protocol
from uuid import UUID

import httpx
from fastapi import Depends, HTTPException, status

from app.auth.dependencies import get_authenticated_context
from app.auth.models import AuthenticatedRequestContext
from app.core.config import Settings, get_settings
from app.knowledge.errors import GatewayError
from app.rag.models import RetrievedChunk

REQUEST_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
EXPECTED_RESULT_FIELDS = {
    "chunk_id",
    "source_id",
    "source_title",
    "source_type",
    "chunk_index",
    "content",
    "locator",
    "similarity",
}


class RetrievalGateway(Protocol):
    async def search(
        self,
        workspace_id: UUID,
        query_embedding: list[float],
        provider_name: str,
        model_name: str,
        dimension: int,
        match_count: int,
    ) -> list[RetrievedChunk]: ...


def _is_positive_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _valid_locator(locator: object) -> bool:
    if not isinstance(locator, dict) or not isinstance(locator.get("kind"), str):
        return False
    kind = locator["kind"]
    if kind == "faq":
        return locator == {"kind": "faq"}
    ranges = {
        "pdf": ("page_start", "page_end", 300),
        "docx": ("block_start", "block_end", 1_000_000),
        "text": ("line_start", "line_end", 1_000_000),
        "markdown": ("line_start", "line_end", 1_000_000),
    }
    if kind not in ranges:
        return False
    start_key, end_key, maximum = ranges[kind]
    if set(locator) != {"kind", start_key, end_key}:
        return False
    start, end = locator[start_key], locator[end_key]
    return _is_positive_integer(start) and _is_positive_integer(end) and start <= end <= maximum


class SupabaseRetrievalGateway:
    """User-scoped access to the single semantic-search RPC."""

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
            "Content-Type": "application/json",
        }

    @staticmethod
    def _provider_code(response: httpx.Response) -> str | None:
        try:
            payload = response.json()
        except ValueError:
            return None
        code = payload.get("code") if isinstance(payload, dict) else None
        return code if isinstance(code, str) and len(code) <= 32 else None

    async def search(
        self,
        workspace_id: UUID,
        query_embedding: list[float],
        provider_name: str,
        model_name: str,
        dimension: int,
        match_count: int,
    ) -> list[RetrievedChunk]:
        try:
            response = await self._client.post(
                f"{self._base_url}/rest/v1/rpc/search_knowledge_chunks",
                headers=self._headers,
                json={
                    "target_workspace_id": str(workspace_id),
                    "query_embedding": query_embedding,
                    "expected_provider": provider_name,
                    "expected_model": model_name,
                    "expected_dimension": dimension,
                    "match_count": match_count,
                },
            )
        except httpx.RequestError as error:
            raise GatewayError("search_knowledge_chunks") from error
        if response.status_code >= 400:
            raise GatewayError("search_knowledge_chunks", self._provider_code(response))
        try:
            payload = response.json()
        except ValueError as error:
            raise GatewayError("search_knowledge_chunks") from error
        return parse_retrieval_rows(payload, "search_knowledge_chunks")


def parse_retrieval_rows(payload: object, operation: str) -> list[RetrievedChunk]:
    """Validate the shared trusted retrieval shape returned by either scoped RPC."""

    if not isinstance(payload, list):
        raise GatewayError(operation)
    matches: list[RetrievedChunk] = []
    for row in payload:
        if not isinstance(row, dict) or set(row) != EXPECTED_RESULT_FIELDS:
            raise GatewayError(operation)
        try:
            chunk_id = UUID(str(row["chunk_id"]))
            source_id = UUID(str(row["source_id"]))
            source_title = row["source_title"]
            source_type = row["source_type"]
            chunk_index = row["chunk_index"]
            content = row["content"]
            locator = row["locator"]
            similarity_value = row["similarity"]
            if (
                not isinstance(source_title, str)
                or not 1 <= len(source_title) <= 200
                or source_type not in {"file", "faq"}
                or not isinstance(chunk_index, int)
                or isinstance(chunk_index, bool)
                or chunk_index < 0
                or not isinstance(content, str)
                or not 1 <= len(content) <= 2200
                or not _valid_locator(locator)
                or isinstance(similarity_value, bool)
                or not isinstance(similarity_value, (int, float))
            ):
                raise ValueError
            similarity = float(similarity_value)
            if not math.isfinite(similarity) or not -1.0 <= similarity <= 1.0:
                raise ValueError
        except (KeyError, TypeError, ValueError) as error:
            raise GatewayError(operation) from error
        matches.append(
            RetrievedChunk(
                chunk_id=chunk_id,
                source_id=source_id,
                source_title=source_title,
                source_type=source_type,
                chunk_index=chunk_index,
                content=content,
                locator=locator,
                similarity=similarity,
            )
        )
    if matches != sorted(
        matches,
        key=lambda match: (-match.similarity, str(match.source_id), match.chunk_index),
    ):
        raise GatewayError(operation)
    return matches


@asynccontextmanager
async def _retrieval_gateway_context(
    settings: Settings,
    context: AuthenticatedRequestContext,
) -> AsyncIterator[SupabaseRetrievalGateway]:
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=False) as client:
        yield SupabaseRetrievalGateway(
            supabase_url=str(settings.supabase_url),
            publishable_key=settings.supabase_publishable_key or "",
            access_token=context.access_token,
            client=client,
        )


async def get_retrieval_gateway(
    context: Annotated[AuthenticatedRequestContext, Depends(get_authenticated_context)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[RetrievalGateway]:
    if settings.supabase_url is None or not settings.supabase_publishable_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Knowledge retrieval is not configured",
        )
    async with _retrieval_gateway_context(settings, context) as gateway:
        yield gateway
