from http import HTTPStatus


class RetrievalHttpError(Exception):
    def __init__(self, detail: str, status_code: int = HTTPStatus.UNPROCESSABLE_ENTITY) -> None:
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


class RagAnswerHttpError(Exception):
    def __init__(self, detail: str, status_code: int = HTTPStatus.BAD_GATEWAY) -> None:
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)
