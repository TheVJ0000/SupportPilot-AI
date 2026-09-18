from types import SimpleNamespace

import pytest

from app.ai.generation.errors import GenerationProviderError
from app.ai.generation.gemini import GeminiGenerationProvider
from app.ai.generation.models import (
    GenerationAnswerDelta,
    GenerationDecisionEvent,
    GenerationEvidence,
    GenerationStreamComplete,
)


class ProviderFailure(Exception):
    def __init__(self, code: int, detail: str = "private provider body and secret") -> None:
        self.code = code
        super().__init__(detail)


class FakeStreamingModels:
    def __init__(self, plans: list[object]) -> None:
        self.plans = list(plans)
        self.calls: list[dict[str, object]] = []

    async def generate_content_stream(self, **kwargs):
        self.calls.append(kwargs)
        plan = self.plans.pop(0)
        if isinstance(plan, Exception):
            raise plan

        async def chunks():
            for item in plan:
                if isinstance(item, Exception):
                    raise item
                yield SimpleNamespace(text=item)

        return chunks()


class FakeClient:
    def __init__(self, plans: list[object]) -> None:
        self.models = FakeStreamingModels(plans)
        self.aio = SimpleNamespace(models=self.models)


def evidence() -> list[GenerationEvidence]:
    return [
        GenerationEvidence(
            evidence_id="E1",
            source_title="Account Help",
            source_type="faq",
            locator={"kind": "faq"},
            content="Use the reset page.",
        ),
        GenerationEvidence(
            evidence_id="E2",
            source_title="Reset timing",
            source_type="faq",
            locator={"kind": "faq"},
            content="Reset links expire after 30 minutes.",
        ),
    ]


def provider(client: FakeClient, sleeps: list[float] | None = None):
    async def capture_sleep(delay: float) -> None:
        if sleeps is not None:
            sleeps.append(delay)

    return GeminiGenerationProvider(
        "not-a-real-key",
        "gemini-3.8-flash",
        client=client,
        sleep=capture_sleep,
    )


async def collect(client: FakeClient):
    return [
        event
        async for event in provider(client).stream_grounded_answer("How do I reset?", evidence())
    ]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_stream_uses_ordered_structured_tool_free_low_thinking_configuration() -> None:
    client = FakeClient([['{"decision":"answerable","evidence_ids":["E1"],"answer":"Reset it."}']])

    events = await collect(client)

    call = client.models.calls[0]
    config = call["config"]
    assert call["model"] == "gemini-3.8-flash"
    assert config.thinking_config is None
    assert config.http_options.extra_body["generationConfig"]["thinkingConfig"] == {
        "thinkingLevel": "LOW"
    }
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema["propertyOrdering"] == [
        "decision",
        "evidence_ids",
        "answer",
    ]
    assert config.tools is None
    assert config.tool_config is None
    assert isinstance(events[0], GenerationDecisionEvent)
    assert isinstance(events[-1], GenerationStreamComplete)


@pytest.mark.anyio
@pytest.mark.parametrize("one_character_chunks", [False, True])
async def test_arbitrary_boundaries_decode_escapes_unicode_and_surrogate_pairs(
    one_character_chunks: bool,
) -> None:
    raw = (
        '{ \n "decision" : "answerable", "evidence_ids" : ["E2", "E1", "E2"], '
        '"answer" : "Quote: \\"yes\\"; path C:\\\\tmp\\nSnowman: \\u2603; '
        'emoji: \\uD83D\\uDE00" }'
    )
    chunks = list(raw) if one_character_chunks else [raw[:37], raw[37:83], raw[83:101], raw[101:]]
    client = FakeClient([chunks])

    events = await collect(client)

    prefix = next(event for event in events if isinstance(event, GenerationDecisionEvent))
    answer = "".join(event.text for event in events if isinstance(event, GenerationAnswerDelta))
    complete = next(event for event in events if isinstance(event, GenerationStreamComplete))
    assert prefix.evidence_ids == ["E1", "E2"]
    assert answer == 'Quote: "yes"; path C:\\tmp\nSnowman: ☃; emoji: 😀'
    assert complete.result.answer == answer


@pytest.mark.anyio
async def test_unknown_evidence_id_prevents_every_answer_delta() -> None:
    client = FakeClient([['{"decision":"answerable","evidence_ids":["E9"],"answer":"Unsafe"}']])
    observed = []

    with pytest.raises(GenerationProviderError, match="generation_invalid_response"):
        async for event in provider(client).stream_grounded_answer("Question?", evidence()):
            observed.append(event)

    assert not any(isinstance(event, GenerationAnswerDelta) for event in observed)


@pytest.mark.anyio
async def test_invalid_final_output_and_oversized_answer_fail_without_completion() -> None:
    for raw in (
        '{"decision":"answerable","evidence_ids":["E1"],"answer":" padded "}',
        '{"decision":"answerable","evidence_ids":["E1"],"answer":"' + ("x" * 4001) + '"}',
    ):
        events = []
        with pytest.raises(GenerationProviderError, match="generation_invalid_response"):
            async for event in provider(FakeClient([[raw]])).stream_grounded_answer(
                "Question?", evidence()
            ):
                events.append(event)
        assert not any(isinstance(event, GenerationStreamComplete) for event in events)


@pytest.mark.anyio
async def test_transient_failure_retries_only_before_the_first_provider_chunk() -> None:
    sleeps: list[float] = []
    client = FakeClient(
        [
            ProviderFailure(503),
            ProviderFailure(429),
            ['{"decision":"answerable","evidence_ids":["E1"],"answer":"Safe"}'],
        ]
    )
    selected = provider(client, sleeps)

    events = [event async for event in selected.stream_grounded_answer("Question?", evidence())]

    assert len(client.models.calls) == 3
    assert sleeps == [0.25, 0.5]
    assert isinstance(events[-1], GenerationStreamComplete)

    after_chunk = FakeClient([["{", ProviderFailure(503)], ['{"decision":"answerable"}']])
    with pytest.raises(GenerationProviderError, match="generation_provider_unavailable") as caught:
        async for _event in provider(after_chunk).stream_grounded_answer("Question?", evidence()):
            pass
    assert len(after_chunk.models.calls) == 1
    assert "private" not in str(caught.value)
    assert "secret" not in str(caught.value)
