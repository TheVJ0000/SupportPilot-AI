import json
from pathlib import Path
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{1,60}$")]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Category = Literal[
    "answerable", "multi_source", "insufficient", "prompt_injection", "context", "adversarial"
]
Scope = Literal["alpha", "beta"]
FactGroup = Annotated[list[Text], Field(min_length=1, max_length=12)]


def identifier(value: str) -> UUID:
    return uuid5(NAMESPACE_URL, "supportpilot-evaluation:" + value)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Source(StrictModel):
    id: Identifier
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    workspace: Scope = "alpha"
    chunks: Annotated[list[Text], Field(min_length=1, max_length=10)]


class ContextTurn(StrictModel):
    role: Literal["customer", "assistant"]
    content: Text


class Case(StrictModel):
    id: Identifier
    category: Category
    security_category: (
        Literal["prompt_injection", "citation_injection", "tenant_isolation"] | None
    ) = None
    question: Text
    workspace: Scope = "alpha"
    expected_answerability: Literal["answerable", "insufficient_evidence"]
    expected_source_ids: Annotated[list[Identifier], Field(max_length=8)]
    retrieval_expected_source_ids: list[Identifier] | None = None
    acceptable_source_ids: list[Identifier] | None = None
    required_fact_groups: Annotated[list[FactGroup], Field(max_length=12)]
    forbidden_fact_groups: Annotated[list[FactGroup], Field(max_length=20)]
    context_turns: Annotated[list[ContextTurn], Field(max_length=20)] = []
    notes: Text
    # Manually authored provider fixtures, NOT predictions from a live model.
    fixture_answer: Annotated[str, StringConstraints(max_length=4000)]
    fixture_chunks: Annotated[list[str], Field(max_length=8)]
    live_generation: bool = False
    live_stream: bool = False

    @property
    def retrieval_sources(self) -> list[str]:
        return (
            self.expected_source_ids
            if self.retrieval_expected_source_ids is None
            else self.retrieval_expected_source_ids
        )

    @property
    def acceptable_sources(self) -> list[str]:
        return (
            self.expected_source_ids
            if self.acceptable_source_ids is None
            else self.acceptable_source_ids
        )

    @model_validator(mode="after")
    def coherent(self):
        for values in (
            self.expected_source_ids,
            self.retrieval_sources,
            self.acceptable_sources,
            self.fixture_chunks,
        ):
            if len(values) != len(set(values)):
                raise ValueError("Duplicate source/chunk annotation")
        if self.expected_answerability == "answerable":
            if not self.required_fact_groups or not self.expected_source_ids:
                raise ValueError("Answerable cases require fact and citation annotations")
        elif self.required_fact_groups or self.expected_source_ids:
            raise ValueError("Insufficient cases cannot require factual answers/citations")
        if not set(self.expected_source_ids) <= set(self.acceptable_sources):
            raise ValueError("Expected citations must be acceptable")
        if self.category == "context" and not self.context_turns:
            raise ValueError("Context cases require turns")
        if self.live_stream and not self.live_generation:
            raise ValueError("Streaming subset must belong to generation subset")
        return self


class Dataset(StrictModel):
    version: Literal["1.0.0"]
    company: Literal["Northstar Outfitters (fictional)"]
    sources: Annotated[list[Source], Field(min_length=9, max_length=30)]
    cases: Annotated[list[Case], Field(min_length=30, max_length=40)]

    @model_validator(mode="after")
    def valid_references(self):
        sources = {source.id: source for source in self.sources}
        if len(sources) != len(self.sources) or len({case.id for case in self.cases}) != len(
            self.cases
        ):
            raise ValueError("Duplicate source or case ID")
        for case in self.cases:
            for source_id in [
                *case.expected_source_ids,
                *case.retrieval_sources,
                *case.acceptable_sources,
            ]:
                if source_id not in sources or sources[source_id].workspace != case.workspace:
                    raise ValueError("Unknown or cross-workspace expected source")
            for reference in case.fixture_chunks:
                source_id, separator, index = reference.partition("/")
                if not separator or source_id not in sources or not index.isdecimal():
                    raise ValueError("Invalid fixture chunk reference")
                source = sources[source_id]
                if int(index) >= len(source.chunks) or source.workspace != case.workspace:
                    raise ValueError("Unknown or cross-workspace fixture chunk")
        return self


def load_dataset(path: Path | None = None) -> Dataset:
    path = path or Path(__file__).with_name("dataset.json")

    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON object key")
            result[key] = value
        return result

    return Dataset.model_validate(
        json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
    )
