import json
from http import HTTPStatus
from uuid import UUID

from pydantic import ValidationError

from app.ai.generation.base import GenerationProvider
from app.ai.generation.errors import GenerationProviderError
from app.ai.generation.models import GenerationEvidence, GroundedGenerationDecision
from app.rag.errors import RagAnswerHttpError
from app.rag.models import GroundedAnswerResponse, RetrievalMatch, TrustedCitation
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


def _insufficient_response(workspace_id: UUID, question: str) -> GroundedAnswerResponse:
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
        if not retrieval.matches:
            return _insufficient_response(workspace_id, retrieval.question)
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

        try:
            raw_decision = await self._generation_provider.generate_grounded_answer(
                retrieval.question,
                labeled_evidence,
            )
            decision = GroundedGenerationDecision.model_validate(raw_decision)
        except GenerationProviderError as error:
            raise _generation_error(error.error_code) from error
        except (TypeError, ValidationError, ValueError) as error:
            raise _generation_error("generation_invalid_response") from error
        except Exception as error:
            raise _generation_error("generation_failed") from error

        if decision.decision == "insufficient_evidence":
            return _insufficient_response(workspace_id, retrieval.question)

        matches_by_id = {
            evidence.evidence_id: match
            for evidence, match in zip(labeled_evidence, retrieval.matches, strict=True)
        }
        requested_ids = set(decision.evidence_ids)
        if not requested_ids.issubset(matches_by_id):
            raise _generation_error("generation_invalid_response")

        citations = [
            _trusted_citation(match)
            for evidence_id, match in matches_by_id.items()
            if evidence_id in requested_ids
        ]
        if not citations:
            raise _generation_error("generation_invalid_response")

        return GroundedAnswerResponse(
            workspace_id=workspace_id,
            question=retrieval.question,
            status="answered",
            answer=decision.answer,
            citations=citations,
        )
