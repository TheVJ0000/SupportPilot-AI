"""Narrow customer API contracts; business/auth/admin errors remain untouched."""

import re
from collections.abc import Callable

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.chat.errors import CustomerChatHttpError

PUBLIC_BODY_MAX_BYTES = 16 * 1024
PUBLIC_PATH = re.compile(
    r"^/api/chat/(?:[^/]+/session|conversations/[^/]+"
    r"(?:/turns(?:/stream)?|/messages/[^/]+/feedback|/human-request)?)$"
)
SAFE_MESSAGES = {
    "invalid_request": "The request is invalid.",
    "invalid_session": "A valid customer session is required.",
    "chat_unavailable": "This support assistant is currently unavailable.",
    "conversation_unavailable": "The conversation is unavailable.",
    "conversation_not_open": "This conversation is not open for this request.",
    "turn_in_progress": "This message is already being processed.",
    "rate_limited": "Too many requests. Please try again shortly.",
    "temporarily_unavailable": "Support is temporarily unavailable. Please try again shortly.",
}


def public_error(status: int, code: str, seconds: int | None = None) -> JSONResponse:
    code = code if code in SAFE_MESSAGES else "temporarily_unavailable"
    error = {"code": code, "message": SAFE_MESSAGES[code]}
    headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
    if status == 429 and code == "rate_limited":
        seconds = seconds if type(seconds) is int and 1 <= seconds <= 3600 else 60
        error["retry_after_seconds"] = seconds
        headers["Retry-After"] = str(seconds)
    return JSONResponse({"error": error}, status_code=status, headers=headers)


def status_code_name(status: int) -> str:
    return {
        400: "invalid_request",
        401: "invalid_session",
        404: "conversation_unavailable",
        409: "conversation_not_open",
        413: "invalid_request",
        415: "invalid_request",
        422: "invalid_request",
        429: "rate_limited",
    }.get(status, "temporarily_unavailable")


class PublicChatRoute(APIRoute):
    def get_route_handler(self) -> Callable:
        original = super().get_route_handler()

        async def handle(request: Request):
            try:
                return await original(request)
            except RequestValidationError:
                return public_error(422, "invalid_request")
            except CustomerChatHttpError as error:
                return public_error(
                    error.status_code,
                    error.code or status_code_name(error.status_code),
                    error.retry_after_seconds,
                )
            except HTTPException as error:
                return public_error(error.status_code, status_code_name(error.status_code))
            except Exception:
                # Never return/log validation, SQL, customer content or provider debug payloads.
                return public_error(500, "temporarily_unavailable")

        return handle


class PublicChatProtection:
    """Bound actual ASGI request bytes before parsing; do not buffer SSE responses."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not PUBLIC_PATH.fullmatch(scope["path"]):
            await self.app(scope, receive, send)
            return

        async def protected_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if "no-store" not in headers.get("Cache-Control", ""):
                    headers["Cache-Control"] = "no-store"
                headers["X-Content-Type-Options"] = "nosniff"
            await send(message)

        if scope["method"] not in {"POST", "PUT"}:
            await self.app(scope, receive, protected_send)
            return
        headers = dict(scope["headers"])
        content_length = headers.get(b"content-length", b"")
        if content_length.isdigit() and (
            len(content_length) > 8 or int(content_length) > PUBLIC_BODY_MAX_BYTES
        ):
            await public_error(413, "invalid_request")(scope, receive, protected_send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > PUBLIC_BODY_MAX_BYTES:
                await public_error(413, "invalid_request")(scope, receive, protected_send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        requires_json = scope["path"].endswith(("/turns", "/turns/stream", "/feedback"))
        media_type = headers.get(b"content-type", b"").split(b";", 1)[0].strip().lower()
        if (body or requires_json) and media_type != b"application/json":
            await public_error(415, "invalid_request")(scope, receive, protected_send)
            return
        delivered = False

        async def bounded_receive() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, protected_send)
