import hashlib
import re
import secrets
from typing import Annotated

from fastapi import Header, HTTPException, status

from app.chat.models import CustomerSessionCredential

CUSTOMER_SESSION_HEADER = "X-SupportPilot-Session"
CUSTOMER_SESSION_TOKEN_BYTES = 32
CUSTOMER_SESSION_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43,128}$")


def generate_customer_session_token() -> str:
    """Generate at least 256 bits of opaque, URL-safe session entropy."""

    return secrets.token_urlsafe(CUSTOMER_SESSION_TOKEN_BYTES)


def hash_customer_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def get_customer_session_credential(
    token: Annotated[str | None, Header(alias=CUSTOMER_SESSION_HEADER)] = None,
) -> CustomerSessionCredential:
    if token is None or CUSTOMER_SESSION_TOKEN_PATTERN.fullmatch(token) is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid customer session is required.",
        )
    return CustomerSessionCredential(token_hash=hash_customer_session_token(token))
