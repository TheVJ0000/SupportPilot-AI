from uuid import UUID

import pytest

from app.ai.generation.errors import GenerationProviderError
from app.ai.generation.models import GroundedGenerationDecision
from app.rag.answering import INSUFFICIENT_EVIDENCE_MESSAGE, RagAnswerService
from app.rag.errors import RagAnswerHttpError
from app.rag.models import RetrievalMatch, RetrievalResponse

WORKSPACE_ID = UUID("20000000-0000-0000-0000-000000000001")
SOURCE_ONE_ID = UUID("30000000-0000-0000-0000-000000000001")
SOURCE_TWO_ID = UUID("30000000-0000-0000-0000-000000000002")


def retrieval_response(*, matches: list[RetrievalMatch] | None = None) -> RetrievalResponse:
    default_matches = [
        RetrievalMatch(
            chunk_id=UUID("40000000-0000-0000-0000-000000000001"),
            source_id=SOURCE_ONE_ID,
            source_title="Account Help",
            source_type="file",
            chunk_index=3,
            content="Use the reset link on the sign-in page.",
            locator={"kind": "pdf", "page_start": 2, "page_end": 2},
            similarity=0.84,
        ),
        RetrievalMatch(
            chunk_id=UUID("40000000-0000-0000-0000-000000000002"),
            source_id=SOURCE_TWO_ID,
            source_title="Reset FAQ",
            source_type="faq",
            chunk_index=0,
            content="Reset links expire after 30 minutes.",
            locator={"kind": "faq"},
            similarity=0.80,
        ),
    ]
    return RetrievalResponse(
        workspace_id=WORKSPACE_ID,
        question="How do I reset my password?",
        matches=default_matches if matches is None else matches,
    )


class FakeRetrievalService:
    def __init__(self, response: RetrievalResponse) -> None:
        self.response = response
        self.calls: list[tuple[UUID, str]] = []

    async def retrieve(self, workspace_id: UUID, question: str) -> RetrievalResponse:
        self.calls.append((workspace_id, question))
        return self.response


class FakeGenerationProvider:
    provider_name = "fake"
    model_name = "fake-grounded-model"

    def __init__(self, result: object = None, error: Exception | None = None) -> None:
        self.result = result or GroundedGenerationDecision(
            decision="answerable",
            answer="Use the reset link; it expires after 30 minutes.",
            evidence_ids=["E1", "E2"],
        )
        self.error = error
        self.calls: list[tuple[str, list]] = []

    async def generate_grounded_answer(self, question: str, evidence: list):
        self.calls.append((question, evidence))
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_no_evidence_skips_generation_and_returns_deterministic_message() -> None:
    retrieval = FakeRetrievalService(retrieval_response(matches=[]))
    generation = FakeGenerationProvider()

    result = await RagAnswerService(retrieval, generation).answer(
        WORKSPACE_ID, "  How do I reset my password?  "
    )

    assert len(retrieval.calls) == 1
    assert generation.calls == []
    assert result.status == "insufficient_evidence"
    assert result.answer == INSUFFICIENT_EVIDENCE_MESSAGE
    assert result.citations == []


@pytest.mark.anyio
async def test_grounded_answer_uses_request_local_labels_and_trusted_citations() -> None:
    retrieval = FakeRetrievalService(retrieval_response())
    generation = FakeGenerationProvider(
        GroundedGenerationDecision(
            decision="answerable",
            answer="Use the reset link.",
            evidence_ids=["E2", "E1", "E2"],
        )
    )

    result = await RagAnswerService(retrieval, generation).answer(
        WORKSPACE_ID, "How do I reset my password?"
    )

    assert len(retrieval.calls) == 1
    assert len(generation.calls) == 1
    question, evidence = generation.calls[0]
    assert question == "How do I reset my password?"
    assert [item.evidence_id for item in evidence] == ["E1", "E2"]
    assert result.status == "answered"
    assert result.answer == "Use the reset link."
    assert [citation.source_id for citation in result.citations] == [
        SOURCE_ONE_ID,
        SOURCE_TWO_ID,
    ]
    assert result.citations[0].source_title == "Account Help"
    assert result.citations[0].chunk_index == 3
    assert result.citations[0].locator == {"kind": "pdf", "page_start": 2, "page_end": 2}
    serialized = result.model_dump_json()
    assert "chunk_id" not in serialized
    assert "similarity" not in serialized
    assert "content" not in serialized


@pytest.mark.anyio
async def test_unknown_model_evidence_id_fails_without_becoming_a_citation() -> None:
    generation = FakeGenerationProvider(
        GroundedGenerationDecision(
            decision="answerable",
            answer="Invented answer.",
            evidence_ids=["E99"],
        )
    )

    with pytest.raises(RagAnswerHttpError) as caught:
        await RagAnswerService(FakeRetrievalService(retrieval_response()), generation).answer(
            WORKSPACE_ID, "Question?"
        )

    assert caught.value.status_code == 502
    assert "E99" not in caught.value.detail
    assert "Invented" not in caught.value.detail


@pytest.mark.anyio
async def test_insufficient_decision_uses_only_server_controlled_response() -> None:
    generation = FakeGenerationProvider(
        GroundedGenerationDecision(
            decision="insufficient_evidence",
            answer="",
            evidence_ids=[],
        )
    )

    result = await RagAnswerService(FakeRetrievalService(retrieval_response()), generation).answer(
        WORKSPACE_ID, "Question?"
    )

    assert result.answer == INSUFFICIENT_EVIDENCE_MESSAGE
    assert result.citations == []


@pytest.mark.anyio
async def test_insufficient_decision_with_generated_answer_is_rejected() -> None:
    generation = FakeGenerationProvider(
        {
            "decision": "insufficient_evidence",
            "answer": "Use my arbitrary general-knowledge answer.",
            "evidence_ids": [],
        }
    )

    with pytest.raises(RagAnswerHttpError) as caught:
        await RagAnswerService(FakeRetrievalService(retrieval_response()), generation).answer(
            WORKSPACE_ID, "Question?"
        )

    assert caught.value.status_code == 502
    assert "general-knowledge" not in caught.value.detail


@pytest.mark.anyio
async def test_provider_failure_is_safe_and_does_not_leak_retrieved_content() -> None:
    generation = FakeGenerationProvider(
        error=GenerationProviderError("generation_provider_unavailable")
    )

    with pytest.raises(RagAnswerHttpError) as caught:
        await RagAnswerService(FakeRetrievalService(retrieval_response()), generation).answer(
            WORKSPACE_ID, "Question?"
        )

    assert caught.value.status_code == 503
    assert "reset link" not in caught.value.detail
    assert "provider payload" not in caught.value.detail


@pytest.mark.anyio
async def test_unexpected_provider_failure_is_sanitized() -> None:
    generation = FakeGenerationProvider(error=RuntimeError("api key and private evidence"))

    with pytest.raises(RagAnswerHttpError) as caught:
        await RagAnswerService(FakeRetrievalService(retrieval_response()), generation).answer(
            WORKSPACE_ID, "Question?"
        )

    assert caught.value.status_code == 502
    assert "private" not in caught.value.detail
    assert "api key" not in caught.value.detail


@pytest.mark.anyio
async def test_oversized_evidence_fails_before_generation() -> None:
    matches = retrieval_response().matches
    matches[0].content = "x" * 20_001
    generation = FakeGenerationProvider()

    with pytest.raises(RagAnswerHttpError, match="safe generation limit"):
        await RagAnswerService(
            FakeRetrievalService(retrieval_response(matches=matches)), generation
        ).answer(WORKSPACE_ID, "Question?")

    assert generation.calls == []
