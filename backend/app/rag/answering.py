import json
from dataclasses import dataclass
from http import HTTPStatus
from uuid import UUID

from pydantic import ValidationError

from app.ai.generation.base import GenerationProvider
from app.ai.generation.errors import GenerationProviderError
from app.ai.generation.models import (
    GenerationDecisionEvent,
    GenerationEvidence,
    GroundedGenerationDecision,
    canonicalize_evidence_ids,
)
from app.rag.errors import RagAnswerHttpError
from app.rag.models import (
    GroundedAnswerResponse,
    RetrievalMatch,
    RetrievalResponse,
    TrustedCitation,
)
from app.rag.service import KnowledgeRetrievalService

MAX_EVIDENCE_CHARS = 20_000
MAX_EVIDENCE_ITEMS = 8
INSUFFICIENT_EVIDENCE_MESSAGE = (
    "I don't have enough information in the available knowledge base to answer that reliably."
)

_GENERATION_MESSAGES = {
    "generation_auth_failed": "AI generation credentials were rejected.",
    "generation_rate_limited": "AI answer generation is temporarily busy. Please try again later.",
    "generation_provider_unavailable": "AI answer generation is temporarily unavailable.",
    "generation_invalid_response": "AI answer generation returned an invalid response.",
    "generation_failed": "The grounded answer could not be generated safely.",
}


@dataclass(frozen=True)
class PreparedGroundedEvidence:
    workspace_id: UUID
    question: str
    matches: list[RetrievalMatch]
    evidence: list[GenerationEvidence]


def insufficient_response(workspace_id: UUID, question: str) -> GroundedAnswerResponse:
    return GroundedAnswerResponse(
        workspace_id=workspace_id,
        question=question,
        status="insufficient_evidence",
        answer=INSUFFICIENT_EVIDENCE_MESSAGE,
        citations=[],
    )


def _generation_error(error_code: str) -> RagAnswerHttpError:
    status_code = (
        HTTPStatus.SERVICE_UNAVAILABLE
        if error_code
        in {
            "generation_auth_failed",
            "generation_rate_limited",
            "generation_provider_unavailable",
        }
        else HTTPStatus.BAD_GATEWAY
    )
    return RagAnswerHttpError(_GENERATION_MESSAGES[error_code], status_code)


def _trusted_citation(match: RetrievalMatch) -> TrustedCitation:
    return TrustedCitation(
        source_id=match.source_id,
        source_title=match.source_title,
        source_type=match.source_type,
        chunk_index=match.chunk_index,
        locator=dict(match.locator),
    )


def _evidence_character_count(evidence: list[GenerationEvidence]) -> int:
    return sum(
        len(item.evidence_id)
        + len(item.source_title)
        + len(item.source_type)
        + len(item.content)
        + len(json.dumps(item.locator, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
        for item in evidence
    )


def prepare_grounded_evidence(
    retrieval: RetrievalResponse,
) -> PreparedGroundedEvidence | None:
    """Apply the shared evidence labels and generation bounds for all RAG flows."""

    if not retrieval.matches:
        return None
    if len(retrieval.matches) > MAX_EVIDENCE_ITEMS or (
        sum(len(match.content) for match in retrieval.matches) > MAX_EVIDENCE_CHARS
    ):
        raise RagAnswerHttpError("Retrieved evidence exceeds the safe generation limit.")
    try:
        labeled_evidence = [
            GenerationEvidence(
                evidence_id=f"E{index}",
                source_title=match.source_title,
                source_type=match.source_type,
                locator=dict(match.locator),
                content=match.content,
            )
            for index, match in enumerate(retrieval.matches, start=1)
        ]
    except (TypeError, ValidationError, ValueError) as error:
        raise RagAnswerHttpError("Retrieved evidence is invalid for generation.") from error
    if _evidence_character_count(labeled_evidence) > MAX_EVIDENCE_CHARS:
        raise RagAnswerHttpError("Retrieved evidence exceeds the safe generation limit.")
    return PreparedGroundedEvidence(
        workspace_id=retrieval.workspace_id,
        question=retrieval.question,
        matches=retrieval.matches,
        evidence=labeled_evidence,
    )


def grounded_response_from_decision(
    prepared: PreparedGroundedEvidence,
    raw_decision: GroundedGenerationDecision,
) -> GroundedAnswerResponse:
    """Validate a provider decision and rebuild citations only from retrieved metadata."""

    try:
        decision = GroundedGenerationDecision.model_validate(raw_decision)
    except (TypeError, ValidationError, ValueError) as error:
        raise _generation_error("generation_invalid_response") from error
    if decision.decision == "insufficient_evidence":
        return insufficient_response(prepared.workspace_id, prepared.question)

    matches_by_id = {
        evidence.evidence_id: match
        for evidence, match in zip(prepared.evidence, prepared.matches, strict=True)
    }
    try:
        canonical_ids = canonicalize_evidence_ids(
            GenerationDecisionEvent(
                decision=decision.decision,
                evidence_ids=decision.evidence_ids,
            ),
            list(matches_by_id),
        )
    except (TypeError, ValidationError, ValueError) as error:
        raise _generation_error("generation_invalid_response") from error
    citations = [_trusted_citation(matches_by_id[evidence_id]) for evidence_id in canonical_ids]
    if not citations:
        raise _generation_error("generation_invalid_response")

    return GroundedAnswerResponse(
        workspace_id=prepared.workspace_id,
        question=prepared.question,
        status="answered",
        answer=decision.answer,
        citations=citations,
    )


class RagAnswerService:
    """Coordinates one retrieval and one bounded, grounded generation decision."""

    def __init__(
        self,
        retrieval_service: KnowledgeRetrievalService,
        generation_provider: GenerationProvider,
    ) -> None:
        self._retrieval_service = retrieval_service
        self._generation_provider = generation_provider

    async def answer(self, workspace_id: UUID, question: str) -> GroundedAnswerResponse:
        retrieval = await self._retrieval_service.retrieve(workspace_id, question)
        prepared = prepare_grounded_evidence(retrieval)
        if prepared is None:
            return insufficient_response(workspace_id, retrieval.question)

        try:
            raw_decision = await self._generation_provider.generate_grounded_answer(
                retrieval.question,
                prepared.evidence,
            )
        except GenerationProviderError as error:
            raise _generation_error(error.error_code) from error
        except Exception as error:
            raise _generation_error("generation_failed") from error
        return grounded_response_from_decision(prepared, raw_decision)
