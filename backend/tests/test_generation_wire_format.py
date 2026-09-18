"""Exercise the installed SDK transport, not just a fake models interface."""

import json

import httpx
import pytest
from google import genai
from google.genai import types

from app.ai.generation.gemini import GeminiGenerationProvider
from app.ai.generation.models import GenerationEvidence, GenerationStreamComplete


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("streaming", [False, True])
async def test_sdk_sends_supported_json_schema_and_preserves_grounded_result(
    streaming: bool,
) -> None:
    requests: list[dict] = []
    answer = {"decision": "answerable", "evidence_ids": ["E1"], "answer": "Reset links expire."}

    def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        assert "gemini-3.8-flash" in request.url.path
        response = {
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": json.dumps(answer)}]},
                    "finishReason": "STOP",
                }
            ]
        }
        if streaming:
            return httpx.Response(
                200,
                text=f"data: {json.dumps(response)}\n\n",
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(200, json=response)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = genai.Client(
            api_key="offline-test-only", http_options=types.HttpOptions(httpx_async_client=http)
        )
        adapter = GeminiGenerationProvider("offline-test-only", "gemini-3.8-flash", client=client)
        evidence = [
            GenerationEvidence(
                evidence_id="E1",
                source_title="Demo FAQ",
                source_type="faq",
                locator={"kind": "faq"},
                content="Reset links expire.",
            )
        ]
        if streaming:
            events = [event async for event in adapter.stream_grounded_answer("Reset?", evidence)]
            assert isinstance(events[-1], GenerationStreamComplete)
            result = events[-1].result
        else:
            result = await adapter.generate_grounded_answer("Reset?", evidence)
        assert result.model_dump() == answer
        assert len(requests) == 1
        payload = requests[0]
        config = payload["generationConfig"]
        assert "responseSchema" not in config
        schema = config["responseJsonSchema"]
        assert schema["additionalProperties"] is False
        assert schema["propertyOrdering"] == ["decision", "evidence_ids", "answer"]
        assert schema["properties"]["evidence_ids"]["maxItems"] == 8
        assert schema["properties"]["answer"]["maxLength"] == 4000
        assert config["responseMimeType"] == "application/json"
        assert config["thinkingConfig"]["thinkingLevel"] == "LOW"
        assert set(config["thinkingConfig"]) == {"thinkingLevel"}
        assert config["maxOutputTokens"] == 1200
        assert "tools" not in payload
        assert "toolConfig" not in payload
