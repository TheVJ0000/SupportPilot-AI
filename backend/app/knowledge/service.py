from http import HTTPStatus
from uuid import UUID

from app.knowledge.chunking import chunk_segments
from app.knowledge.errors import ExtractionError, GatewayError, ProcessingHttpError
from app.knowledge.extraction import extract_source
from app.knowledge.gateway import KnowledgeGateway
from app.knowledge.models import ProcessingResult, ProcessingSource
from app.knowledge.normalization import normalize_segments

_SAFE_FAILURE_MESSAGES = {
    "invalid_file_content": "The uploaded file content does not match a supported document.",
    "unsupported_encoding": "Text and Markdown sources must use UTF-8 encoding.",
    "encrypted_pdf": "Encrypted or password-protected PDFs are not supported.",
    "too_many_pages": "PDF sources may contain at most 300 pages.",
    "document_too_large": "The document exceeds a safe processing limit.",
    "no_extractable_text": "No extractable text was found in this source.",
    "malformed_document": "The uploaded document is malformed or unsafe to process.",
    "storage_download_failed": "The private source file could not be downloaded safely.",
    "extraction_failed": "The source could not be extracted safely.",
    "chunking_failed": "The extracted text could not be chunked safely.",
}


class KnowledgeProcessingService:
    def __init__(self, gateway: KnowledgeGateway) -> None:
        self._gateway = gateway

    @staticmethod
    def _validate_trusted_file_path(source: ProcessingSource) -> None:
        if not source.storage_path or not source.original_filename:
            raise ExtractionError("malformed_document")
        extension = source.original_filename.rsplit(".", maxsplit=1)[-1].lower()
        expected_path = f"{source.workspace_id}/{source.source_id}/{source.source_id}.{extension}"
        if source.storage_path != expected_path:
            raise ExtractionError("malformed_document")

    async def _record_failure(self, source_id: UUID, error_code: str) -> None:
        try:
            await self._gateway.fail_extraction(source_id, error_code)
        except Exception:
            pass

    async def process(self, source_id: UUID) -> ProcessingResult:
        try:
            source = await self._gateway.begin_extraction(source_id)
        except GatewayError as error:
            if error.provider_code == "42501":
                raise ProcessingHttpError(
                    "Knowledge management permission is required.", HTTPStatus.FORBIDDEN
                ) from error
            raise ProcessingHttpError(
                "This source cannot be processed in its current state.", HTTPStatus.CONFLICT
            ) from error

        try:
            content = None
            if source.source_type == "file":
                self._validate_trusted_file_path(source)
                try:
                    content = await self._gateway.download_source(source.storage_path or "")
                except GatewayError as error:
                    failure_code = (
                        "document_too_large"
                        if error.operation == "download_too_large"
                        else "storage_download_failed"
                    )
                    raise ExtractionError(failure_code) from error

            segments = extract_source(source, content)
            normalized_segments, extracted_char_count = normalize_segments(segments)
            chunks = chunk_segments(normalized_segments)
            try:
                await self._gateway.complete_extraction(
                    source.source_id, chunks, extracted_char_count
                )
            except GatewayError as error:
                await self._record_failure(source.source_id, "extraction_failed")
                raise ProcessingHttpError(
                    "Knowledge processing could not be completed safely.",
                    HTTPStatus.BAD_GATEWAY,
                ) from error
        except ProcessingHttpError:
            raise
        except ExtractionError as error:
            await self._record_failure(source.source_id, error.error_code)
            raise ProcessingHttpError(_SAFE_FAILURE_MESSAGES[error.error_code]) from error
        except Exception as error:
            await self._record_failure(source.source_id, "extraction_failed")
            raise ProcessingHttpError(_SAFE_FAILURE_MESSAGES["extraction_failed"]) from error

        return ProcessingResult(
            source_id=source.source_id,
            chunk_count=len(chunks),
            extracted_char_count=extracted_char_count,
        )
