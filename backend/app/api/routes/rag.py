from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.ai.embeddings.base import EmbeddingProvider
from app.ai.embeddings.factory import get_embedding_provider
from app.ai.generation.base import GenerationProvider
from app.ai.generation.factory import get_generation_provider
from app.auth.dependencies import get_authenticated_context
from app.auth.models import AuthenticatedRequestContext
from app.rag.answering import RagAnswerService
from app.rag.errors import RagAnswerHttpError, RetrievalHttpError
from app.rag.gateway import RetrievalGateway, get_retrieval_gateway
from app.rag.models import (
    GroundedAnswerRequest,
    GroundedAnswerResponse,
    RetrievalRequest,
    RetrievalResponse,
)
from app.rag.service import KnowledgeRetrievalService

router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("/retrieve", response_model=RetrievalResponse)
async def retrieve_knowledge(
    request: RetrievalRequest,
    _context: Annotated[AuthenticatedRequestContext, Depends(get_authenticated_context)],
    gateway: Annotated[RetrievalGateway, Depends(get_retrieval_gateway)],
    provider: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
) -> RetrievalResponse:
    try:
        return await KnowledgeRetrievalService(gateway, provider).retrieve(
            request.workspace_id, request.question
        )
    except RetrievalHttpError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


@router.post("/answer", response_model=GroundedAnswerResponse)
async def answer_question(
    request: GroundedAnswerRequest,
    _context: Annotated[AuthenticatedRequestContext, Depends(get_authenticated_context)],
    generation_provider: Annotated[GenerationProvider, Depends(get_generation_provider)],
    gateway: Annotated[RetrievalGateway, Depends(get_retrieval_gateway)],
    embedding_provider: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
) -> GroundedAnswerResponse:
    retrieval_service = KnowledgeRetrievalService(gateway, embedding_provider)
    try:
        return await RagAnswerService(retrieval_service, generation_provider).answer(
            request.workspace_id,
            request.question,
        )
    except (RagAnswerHttpError, RetrievalHttpError) as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
