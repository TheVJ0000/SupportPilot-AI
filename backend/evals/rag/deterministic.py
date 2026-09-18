"""Independent lexical retrieval diagnostic + scripted SDK contract responses.

Not semantic/Gemini/pgvector quality. Ranking never reads case annotations.
Generation is manually authored fixture prose, not a model prediction.
"""

import hashlib
import json
import math
import re
from types import SimpleNamespace

from app.ai.generation.gemini import GeminiGenerationProvider
from app.rag.models import RetrievedChunk

from .models import Case, Dataset, identifier

STOP = frozenset(
    (
        "a an the is are to of in for and or what how when does do i it my your you with can "
        "within from at as on that about not before after current customer question "
        "previous assistant"
    ).split()
)


def vector(text: str) -> list[float]:
    values = [0.0] * 768
    for word in re.findall(r"\w+", text.casefold()):
        if word in STOP:
            continue
        index = int.from_bytes(hashlib.blake2b(word.encode(), digest_size=4).digest(), "big") % 768
        values[index] += 1
    length = math.sqrt(sum(value * value for value in values))
    return [value / length if length else 0.0 for value in values]


class Embeddings:
    provider_name = "fixture-lexical"
    model_name = "hashed-bag-of-words"
    dimension = 768

    async def embed_query(self, query):
        return vector(query)


def corpus_chunks(dataset: Dataset):
    for source in dataset.sources:
        for index, text in enumerate(source.chunks):
            yield source, index, text


class Gateway:
    def __init__(self, dataset: Dataset):
        self.dataset = dataset

    async def search(
        self, workspace_id, query_embedding, provider_name, model_name, dimension, match_count
    ):
        matches = []
        for source, index, text in corpus_chunks(self.dataset):
            if identifier(source.workspace) != workspace_id:
                continue
            score = sum(
                left * right
                for left, right in zip(
                    query_embedding, vector(source.title + " " + text), strict=True
                )
            )
            matches.append(
                RetrievedChunk(
                    identifier(f"{source.id}/{index}"),
                    identifier(source.id),
                    source.title,
                    "faq",
                    index,
                    text,
                    {"kind": "faq"},
                    score,
                )
            )
        return sorted(
            matches, key=lambda match: (-match.similarity, str(match.source_id), match.chunk_index)
        )[:match_count]


class ScriptedModels:
    def __init__(self, dataset: Dataset, case: Case):
        self.dataset, self.case = dataset, case

    def decision(self, contents):
        evidence = json.loads(contents.parts[0].text)["evidence"]
        sources = {source.id: source for source in self.dataset.sources}
        labels = []
        for reference in self.case.fixture_chunks:
            slug, index = reference.split("/")
            source = sources[slug]
            match = next(
                (
                    item
                    for item in evidence
                    if item["source_title"] == source.title
                    and item["content"] == source.chunks[int(index)]
                ),
                None,
            )
            if match is None:
                return dict(decision="insufficient_evidence", evidence_ids=[], answer="")
            labels.append(match["evidence_id"])
        return dict(
            decision="answerable" if labels else "insufficient_evidence",
            evidence_ids=labels,
            answer=self.case.fixture_answer if labels else "",
        )

    async def generate_content(self, *, contents, **kwargs):
        return SimpleNamespace(parsed=self.decision(contents))

    async def generate_content_stream(self, *, contents, **kwargs):
        raw = json.dumps(self.decision(contents), ensure_ascii=False)

        async def chunks():
            for index in range(0, len(raw), 13):
                yield SimpleNamespace(text=raw[index : index + 13])

        return chunks()


def generation(dataset: Dataset, case: Case):
    models = ScriptedModels(dataset, case)
    return GeminiGenerationProvider(
        "synthetic-sdk-placeholder",
        "gemini-3.8-flash",
        client=SimpleNamespace(aio=SimpleNamespace(models=models)),
    )
