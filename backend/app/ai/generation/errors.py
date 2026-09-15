ALLOWED_GENERATION_FAILURE_CODES = frozenset(
    {
        "generation_auth_failed",
        "generation_rate_limited",
        "generation_provider_unavailable",
        "generation_invalid_response",
        "generation_failed",
    }
)


class GenerationProviderError(Exception):
    """A generation failure safe to return without provider details."""

    def __init__(self, error_code: str) -> None:
        if error_code not in ALLOWED_GENERATION_FAILURE_CODES:
            error_code = "generation_failed"
        self.error_code = error_code
        super().__init__(error_code)
