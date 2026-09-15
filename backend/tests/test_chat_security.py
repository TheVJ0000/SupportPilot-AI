import base64
import hashlib
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.chat.models import CustomerSessionCredential
from app.chat.security import (
    CUSTOMER_SESSION_HEADER,
    generate_customer_session_token,
    get_customer_session_credential,
    hash_customer_session_token,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_customer_session_token_has_at_least_256_bits_and_hashes_with_sha256() -> None:
    token = generate_customer_session_token()
    padding = "=" * (-len(token) % 4)
    decoded = base64.urlsafe_b64decode(token + padding)

    assert len(decoded) >= 32
    assert len(token) >= 43
    assert hash_customer_session_token(token) == hashlib.sha256(token.encode()).hexdigest()
    assert len(hash_customer_session_token(token)) == 64
    assert token not in repr(CustomerSessionCredential(token_hash="a" * 64))


@pytest.mark.anyio
async def test_customer_session_header_is_required_and_raw_token_is_discarded() -> None:
    test_app = FastAPI()

    @test_app.get("/credential")
    async def credential(
        context: Annotated[CustomerSessionCredential, Depends(get_customer_session_credential)],
    ):
        return {"token_hash": context.token_hash}

    token = generate_customer_session_token()
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        missing = await client.get("/credential")
        malformed = await client.get(
            "/credential", headers={CUSTOMER_SESSION_HEADER: "raw token with spaces"}
        )
        valid = await client.get("/credential", headers={CUSTOMER_SESSION_HEADER: token})

    assert missing.status_code == 401
    assert malformed.status_code == 401
    assert valid.status_code == 200
    assert valid.json() == {"token_hash": hash_customer_session_token(token)}
    assert token not in valid.text
