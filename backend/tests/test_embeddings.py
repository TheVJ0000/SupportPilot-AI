from types import SimpleNamespace

import pytest

from app.ai.embeddings.base import EmbeddingDocument
from app.ai.embeddings.errors import EmbeddingProviderError
from app.ai.embeddings.gemini import GeminiEmbeddingProvider


class ProviderFailure(Exception):
    def __init__(self, code: int, detail: str = "private provider detail") -> None:
        self.code = code
        super().__init__(detail)


class FakeModels:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    async def embed_content(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeClient:
    def __init__(self, responses: list[object]) -> None:
        self.models = FakeModels(responses)
        self.aio = SimpleNamespace(models=self.models)


def response(count: int, dimension: int = 768, value: object = 0.25):
    return SimpleNamespace(
        embeddings=[SimpleNamespace(values=[value] * dimension) for _ in range(count)]
    )


def provider(client: FakeClient, **kwargs) -> GeminiEmbeddingProvider:
    return GeminiEmbeddingProvider(
        "not-a-real-key",
        "gemini-embedding-2",
        768,
        client=client,
        sleep=kwargs.get("sleep", no_sleep),
    )


async def no_sleep(_delay: float) -> None:
    return None


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_requests_model_dimension_and_retrieval_document_format() -> None:
    client = FakeClient([response(2)])
    result = await provider(client).embed_documents(
        [EmbeddingDocument("First", "Support | Guide"), EmbeddingDocument("Second")]
    )

    assert len(result) == 2
    call = client.models.calls[0]
    assert call["model"] == "gemini-embedding-2"
    assert call["config"].output_dimensionality == 768
    assert [item.parts[0].text for item in call["contents"]] == [
        "title: Support   Guide | text: First",
        "title: none | text: Second",
    ]


@pytest.mark.anyio
async def test_batching_preserves_document_order() -> None:
    client = FakeClient([response(24, value=1), response(1, value=2)])
    documents = [EmbeddingDocument(f"Chunk {index}") for index in range(25)]

    result = await provider(client).embed_documents(documents)

    assert len(client.models.calls) == 2
    assert len(client.models.calls[0]["contents"]) == 24
    assert result[0][0] == 1.0
    assert result[-1][0] == 2.0


@pytest.mark.anyio
@pytest.mark.parametrize(
    "bad_response",
    [
        response(1),
        response(2, 767),
        response(2, value=float("nan")),
        response(2, value=float("inf")),
        response(2, value="x"),
    ],
)
async def test_invalid_provider_responses_are_rejected(bad_response: object) -> None:
    with pytest.raises(EmbeddingProviderError, match="embedding_invalid_response"):
        await provider(FakeClient([bad_response])).embed_documents(
            [EmbeddingDocument("one"), EmbeddingDocument("two")]
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status_code", "expected"),
    [(401, "embedding_auth_failed"), (429, "embedding_rate_limited")],
)
async def test_provider_errors_are_sanitized(status_code: int, expected: str) -> None:
    client = FakeClient([ProviderFailure(status_code)] * 3)
    with pytest.raises(EmbeddingProviderError, match=expected) as caught:
        await provider(client).embed_documents([EmbeddingDocument("private source content")])

    assert "private" not in str(caught.value)
    assert len(client.models.calls) == (3 if status_code == 429 else 1)


@pytest.mark.anyio
async def test_transient_retry_is_bounded_and_can_recover() -> None:
    sleeps: list[float] = []

    async def capture_sleep(delay: float) -> None:
        sleeps.append(delay)

    client = FakeClient([ProviderFailure(503), ProviderFailure(503), response(1)])
    result = await provider(client, sleep=capture_sleep).embed_documents(
        [EmbeddingDocument("synthetic content")]
    )

    assert len(result) == 1
    assert sleeps == [0.25, 0.5]


@pytest.mark.anyio
async def test_query_uses_exact_question_answering_format_and_dimension() -> None:
    client = FakeClient([response(1)])

    vector = await provider(client).embed_query("How do I reset my password?")

    call = client.models.calls[0]
    assert call["model"] == "gemini-embedding-2"
    assert call["config"].output_dimensionality == 768
    assert [item.parts[0].text for item in call["contents"]] == [
        "task: question answering | query: How do I reset my password?"
    ]
    assert len(vector) == 768


@pytest.mark.anyio
async def test_query_rejects_blank_and_invalid_vectors() -> None:
    blank_client = FakeClient([])
    with pytest.raises(EmbeddingProviderError, match="embedding_invalid_response"):
        await provider(blank_client).embed_query("   ")
    assert blank_client.models.calls == []

    for invalid_response in (
        response(2),
        response(1, 767),
        response(1, value=float("nan")),
        response(1, value=float("inf")),
    ):
        with pytest.raises(EmbeddingProviderError, match="embedding_invalid_response"):
            await provider(FakeClient([invalid_response])).embed_query("Synthetic question")


@pytest.mark.anyio
async def test_query_rate_limit_retries_are_bounded_and_sanitized() -> None:
    client = FakeClient([ProviderFailure(429, "secret key and provider payload")] * 3)

    with pytest.raises(EmbeddingProviderError, match="embedding_rate_limited") as caught:
        await provider(client).embed_query("Synthetic question")

    assert len(client.models.calls) == 3
    assert "secret" not in str(caught.value)


@pytest.mark.anyio
async def test_query_auth_failure_does_not_retry() -> None:
    client = FakeClient([ProviderFailure(401, "private credential detail")])

    with pytest.raises(EmbeddingProviderError, match="embedding_auth_failed"):
        await provider(client).embed_query("Synthetic question")

    assert len(client.models.calls) == 1
