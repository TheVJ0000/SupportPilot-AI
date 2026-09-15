from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

MAX_GENERATED_ANSWER_CHARS = 4000
MAX_GENERATION_EVIDENCE = 8

EvidenceId = Annotated[
    str,
    StringConstraints(pattern=r"^E[1-9][0-9]*$", max_length=10),
]


class GenerationEvidence(BaseModel):
    """Minimal, request-local evidence supplied to a generation provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: EvidenceId
    source_title: str = Field(min_length=1, max_length=200)
    source_type: Literal["file", "faq"]
    locator: dict[str, Any]
    content: str = Field(min_length=1, max_length=2200)


class GroundedGenerationDecision(BaseModel):
    """Strict provider result; citation metadata is deliberately absent."""

    model_config = ConfigDict(extra="forbid", revalidate_instances="always")

    decision: Literal["answerable", "insufficient_evidence"]
    answer: str = Field(max_length=MAX_GENERATED_ANSWER_CHARS)
    evidence_ids: list[EvidenceId] = Field(max_length=MAX_GENERATION_EVIDENCE)

    @model_validator(mode="after")
    def validate_decision(self) -> "GroundedGenerationDecision":
        self.answer = self.answer.strip()
        if self.decision == "answerable":
            if not self.answer or not self.evidence_ids:
                raise ValueError("Answerable decisions require an answer and evidence")
        elif self.answer or self.evidence_ids:
            raise ValueError("Insufficient-evidence decisions cannot contain an answer or evidence")
        return self
