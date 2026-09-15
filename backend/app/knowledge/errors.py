from http import HTTPStatus

ALLOWED_FAILURE_CODES = frozenset(
    {
        "invalid_file_content",
        "unsupported_encoding",
        "encrypted_pdf",
        "too_many_pages",
        "document_too_large",
        "no_extractable_text",
        "malformed_document",
        "storage_download_failed",
        "extraction_failed",
        "chunking_failed",
    }
)


class ExtractionError(Exception):
    def __init__(self, error_code: str) -> None:
        if error_code not in ALLOWED_FAILURE_CODES:
            error_code = "extraction_failed"
        self.error_code = error_code
        super().__init__(error_code)


class GatewayError(Exception):
    """A sanitized failure from one of the narrowly allowed Supabase operations."""

    def __init__(self, operation: str, provider_code: str | None = None) -> None:
        self.operation = operation
        self.provider_code = provider_code
        super().__init__(operation)


class ProcessingHttpError(Exception):
    def __init__(
        self,
        detail: str,
        status_code: int = HTTPStatus.UNPROCESSABLE_ENTITY,
    ) -> None:
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)
