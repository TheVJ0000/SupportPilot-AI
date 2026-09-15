ALLOWED_EMBEDDING_FAILURE_CODES = frozenset(
    {
        "embedding_auth_failed",
        "embedding_rate_limited",
        "embedding_provider_unavailable",
        "embedding_invalid_response",
        "embedding_failed",
    }
)


class EmbeddingProviderError(Exception):
    """A provider failure safe to persist and return without provider details."""

    def __init__(self, error_code: str) -> None:
        if error_code not in ALLOWED_EMBEDDING_FAILURE_CODES:
            error_code = "embedding_failed"
        self.error_code = error_code
        super().__init__(error_code)
