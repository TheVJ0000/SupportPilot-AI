from http import HTTPStatus


class CustomerChatGatewayError(Exception):
    """Sanitized failure from an approved customer-chat RPC."""

    def __init__(
        self,
        operation: str,
        provider_code: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        self.operation = operation
        self.provider_code = provider_code
        self.retry_after_seconds = retry_after_seconds
        super().__init__(operation)


class CustomerChatHttpError(Exception):
    def __init__(
        self,
        detail: str,
        status_code: int = HTTPStatus.BAD_GATEWAY,
        *,
        code: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        self.detail = detail
        self.status_code = status_code
        self.code = code
        self.retry_after_seconds = retry_after_seconds
        super().__init__(detail)
