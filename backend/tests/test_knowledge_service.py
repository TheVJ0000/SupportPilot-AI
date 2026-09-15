from uuid import UUID

import pytest

from app.knowledge.errors import GatewayError, ProcessingHttpError
from app.knowledge.models import KnowledgeChunk, ProcessingSource
from app.knowledge.service import KnowledgeProcessingService

SOURCE_ID = UUID("30000000-0000-0000-0000-000000000001")
WORKSPACE_ID = UUID("20000000-0000-0000-0000-000000000001")


class FakeGateway:
    def __init__(self, source: ProcessingSource, content: bytes | None = None) -> None:
        self.source = source
        self.content = content
        self.begun_with: UUID | None = None
        self.downloaded_path: str | None = None
        self.completed: tuple[UUID, list[KnowledgeChunk], int] | None = None
        self.failures: list[tuple[UUID, str]] = []
        self.download_error: GatewayError | None = None
        self.completion_error: GatewayError | None = None
        self.failure_error: GatewayError | None = None

    async def begin_extraction(self, source_id: UUID) -> ProcessingSource:
        self.begun_with = source_id
        return self.source

    async def download_source(self, storage_path: str) -> bytes:
        self.downloaded_path = storage_path
        if self.download_error:
            raise self.download_error
        return self.content or b""

    async def complete_extraction(
        self, source_id: UUID, chunks: list[KnowledgeChunk], extracted_char_count: int
    ) -> None:
        if self.completion_error:
            raise self.completion_error
        self.completed = (source_id, chunks, extracted_char_count)

    async def fail_extraction(self, source_id: UUID, error_code: str) -> None:
        if self.failure_error:
            raise self.failure_error
        self.failures.append((source_id, error_code))


def faq_source() -> ProcessingSource:
    return ProcessingSource(
        source_id=SOURCE_ID,
        workspace_id=WORKSPACE_ID,
        source_type="faq",
        storage_path=None,
        original_filename=None,
        mime_type=None,
        byte_size=None,
        faq_question="How do refunds work?",
        faq_answer="Use the synthetic returns form.",
    )


def text_source(byte_size: int) -> ProcessingSource:
    storage_path = f"{WORKSPACE_ID}/{SOURCE_ID}/{SOURCE_ID}.txt"
    return ProcessingSource(
        source_id=SOURCE_ID,
        workspace_id=WORKSPACE_ID,
        source_type="file",
        storage_path=storage_path,
        original_filename="guide.txt",
        mime_type="text/plain",
        byte_size=byte_size,
        faq_question=None,
        faq_answer=None,
    )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_successful_faq_processing_completes_without_storage_download() -> None:
    gateway = FakeGateway(faq_source())

    result = await KnowledgeProcessingService(gateway).process(SOURCE_ID)

    assert result.status == "pending"
    assert result.next_stage == "embedding"
    assert result.chunk_count == 1
    assert gateway.downloaded_path is None
    assert gateway.completed is not None
    assert gateway.completed[1][0].locator == {"kind": "faq"}
    assert gateway.failures == []


@pytest.mark.anyio
async def test_successful_file_processing_downloads_and_completes() -> None:
    content = b"First paragraph.\n\nSecond paragraph."
    gateway = FakeGateway(text_source(len(content)), content)

    result = await KnowledgeProcessingService(gateway).process(SOURCE_ID)

    assert result.extracted_char_count == len(content.decode())
    assert gateway.downloaded_path == gateway.source.storage_path
    assert gateway.completed is not None


@pytest.mark.anyio
async def test_extraction_failure_records_safe_code() -> None:
    content = b"binary\x00content"
    gateway = FakeGateway(text_source(len(content)), content)

    with pytest.raises(ProcessingHttpError) as caught:
        await KnowledgeProcessingService(gateway).process(SOURCE_ID)

    assert caught.value.detail == "The uploaded file content does not match a supported document."
    assert gateway.failures == [(SOURCE_ID, "invalid_file_content")]


@pytest.mark.anyio
async def test_download_failure_is_sanitized_and_marks_source_failed() -> None:
    gateway = FakeGateway(text_source(10))
    gateway.download_error = GatewayError("download_source", "private-provider-code")

    with pytest.raises(ProcessingHttpError) as caught:
        await KnowledgeProcessingService(gateway).process(SOURCE_ID)

    assert "private-provider-code" not in caught.value.detail
    assert gateway.failures == [(SOURCE_ID, "storage_download_failed")]


@pytest.mark.anyio
async def test_completion_failure_never_reports_success_and_marks_source_failed() -> None:
    gateway = FakeGateway(faq_source())
    gateway.completion_error = GatewayError("complete_knowledge_extraction")

    with pytest.raises(ProcessingHttpError) as caught:
        await KnowledgeProcessingService(gateway).process(SOURCE_ID)

    assert caught.value.status_code == 502
    assert gateway.failures == [(SOURCE_ID, "extraction_failed")]


@pytest.mark.anyio
async def test_failure_rpc_outage_preserves_the_original_safe_error() -> None:
    content = b"binary\x00content"
    gateway = FakeGateway(text_source(len(content)), content)
    gateway.failure_error = GatewayError("fail_knowledge_extraction", "private-database-detail")

    with pytest.raises(ProcessingHttpError) as caught:
        await KnowledgeProcessingService(gateway).process(SOURCE_ID)

    assert caught.value.detail == "The uploaded file content does not match a supported document."
    assert "private" not in caught.value.detail


@pytest.mark.anyio
async def test_download_size_must_match_trusted_metadata() -> None:
    content = b"valid UTF-8 text"
    gateway = FakeGateway(text_source(len(content) + 1), content)

    with pytest.raises(ProcessingHttpError) as caught:
        await KnowledgeProcessingService(gateway).process(SOURCE_ID)

    assert caught.value.detail == "The uploaded file content does not match a supported document."
    assert gateway.failures == [(SOURCE_ID, "invalid_file_content")]
