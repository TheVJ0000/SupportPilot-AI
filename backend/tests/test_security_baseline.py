"""Deterministic security boundaries, not live AI evaluation or penetration tests."""

from datetime import UTC, datetime, timedelta
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
import jwt
import pytest
from test_knowledge_extraction import docx_bytes

from app.auth import verifier as verifier_module
from app.auth.verifier import (
    AuthenticationError,
    AuthenticationServiceUnavailableError,
    SupabaseTokenVerifier,
)
from app.knowledge.errors import ExtractionError
from app.knowledge.extraction import extract_docx

USER = "10000000-0000-4000-8000-000000000001"
ISSUER = "https://project.example.test/auth/v1"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def legacy_token(**overrides):
    claims = {
        "iss": ISSUER,
        "aud": "authenticated",
        "sub": USER,
        "exp": datetime.now(UTC) + timedelta(minutes=5),
        **overrides,
    }
    return jwt.encode(
        {key: value for key, value in claims.items() if value is not None},
        "synthetic-hs256-signing-value-never-used-in-production",
        algorithm="HS256",
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "status,payload,expected",
    [
        (200, {"id": USER}, None),
        (401, {}, AuthenticationError),
        (403, {}, AuthenticationError),
        (503, {}, AuthenticationServiceUnavailableError),
        (200, [], AuthenticationServiceUnavailableError),
        (200, None, AuthenticationServiceUnavailableError),
        (200, {"id": "20000000-0000-4000-8000-000000000002"}, AuthenticationError),
    ],
)
async def test_legacy_signature_requires_auth_server_and_identity_binding(
    monkeypatch, status, payload, expected
):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(verifier_module.httpx, "AsyncClient", lambda **kwargs: client)
    verifier = SupabaseTokenVerifier("https://project.example.test", "synthetic-publishable-value")
    if expected:
        with pytest.raises(expected):
            await verifier.verify(legacy_token())
    else:
        assert str((await verifier.verify(legacy_token())).user_id) == USER
    assert len(requests) == 1
    assert str(requests[0].url) == ISSUER + "/user"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://other.example.test/auth/v1"},
        {"aud": "service_role"},
        {"exp": datetime.now(UTC) - timedelta(minutes=1)},
        {"exp": None},
        {"exp": []},
        {"exp": float("inf")},
        {"sub": None},
        {"sub": "not-a-uuid"},
    ],
)
async def test_legacy_claim_validation_never_relies_on_unverified_decode(monkeypatch, claims):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"id": USER}))
    )
    monkeypatch.setattr(verifier_module.httpx, "AsyncClient", lambda **kwargs: client)
    with pytest.raises(AuthenticationError):
        await SupabaseTokenVerifier("https://project.example.test", "synthetic-value").verify(
            legacy_token(**claims)
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "token",
    ["not-a-jwt", "", "eyJ.invalid.payload", jwt.encode({"sub": USER}, key="", algorithm="none")],
)
async def test_malformed_and_unsigned_jwt_rejected_without_network(token):
    with pytest.raises(AuthenticationError):
        await SupabaseTokenVerifier("https://project.example.test", "synthetic-value").verify(token)


def replace_docx_member(name, content):
    output = BytesIO()
    with ZipFile(BytesIO(docx_bytes())) as original, ZipFile(output, "w", ZIP_DEFLATED) as modified:
        for member in original.infolist():
            modified.writestr(
                member.filename, content if member.filename == name else original.read(member)
            )
    return output.getvalue()


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
@pytest.mark.parametrize(
    "mode", ['TargetMode = "External"', "TargetMode='External'", 'TargetMode="&#69;xternal"']
)
def test_docx_external_relationships_reject_encodings_and_attribute_variants(encoding, mode):
    xml = (
        f'<?xml version="1.0" encoding="{encoding}"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="hyperlink" '
        f'Target="https://synthetic.example.test" {mode}/></Relationships>'
    )
    with pytest.raises(ExtractionError, match="invalid_file_content"):
        extract_docx(replace_docx_member("word/_rels/document.xml.rels", xml.encode(encoding)))


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_docx_dtd_is_rejected_without_entity_resolution(encoding):
    with ZipFile(BytesIO(docx_bytes())) as archive:
        document = archive.read("word/document.xml").decode("utf-8")
    document = document[document.index("?>") + 2 :]
    xml = (
        f'<?xml version="1.0" encoding="{encoding}"?>'
        f'<!DOCTYPE w:document [<!ENTITY data "synthetic">]>{document}'
    )
    with pytest.raises(ExtractionError, match="invalid_file_content"):
        extract_docx(replace_docx_member("word/document.xml", xml.encode(encoding)))
