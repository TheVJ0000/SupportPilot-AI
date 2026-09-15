from http import HTTPStatus


class CustomerChatGatewayError(Exception):
    """Sanitized failure from an approved customer-chat RPC."""

    def __init__(self, operation: str, provider_code: str | None = None) -> None:
        self.operation = operation
        self.provider_code = provider_code
        super().__init__(operation)


class CustomerChatHttpError(Exception):
    def __init__(self, detail: str, status_code: int = HTTPStatus.BAD_GATEWAY) -> None:
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)
