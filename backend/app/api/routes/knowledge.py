from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.ai.embeddings.base import EmbeddingProvider
from app.ai.embeddings.factory import get_embedding_provider
from app.auth.dependencies import get_authenticated_context
from app.auth.models import AuthenticatedRequestContext
from app.knowledge.errors import ProcessingHttpError
from app.knowledge.gateway import KnowledgeGateway, get_knowledge_gateway
from app.knowledge.indexing import KnowledgeIndexingService
from app.knowledge.models import IndexingResult, ProcessingResult
from app.knowledge.service import KnowledgeProcessingService

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.post("/{source_id}/process", response_model=ProcessingResult)
async def process_knowledge_source(
    source_id: UUID,
    _context: Annotated[AuthenticatedRequestContext, Depends(get_authenticated_context)],
    gateway: Annotated[KnowledgeGateway, Depends(get_knowledge_gateway)],
) -> ProcessingResult:
    try:
        return await KnowledgeProcessingService(gateway).process(source_id)
    except ProcessingHttpError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


@router.post("/{source_id}/index", response_model=IndexingResult)
async def index_knowledge_source(
    source_id: UUID,
    _context: Annotated[AuthenticatedRequestContext, Depends(get_authenticated_context)],
    gateway: Annotated[KnowledgeGateway, Depends(get_knowledge_gateway)],
    provider: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
) -> IndexingResult:
    try:
        return await KnowledgeIndexingService(gateway, provider).index(source_id)
    except ProcessingHttpError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
