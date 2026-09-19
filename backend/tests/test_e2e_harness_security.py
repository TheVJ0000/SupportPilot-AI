"""Executable regression guards: test tooling must never alter production auth."""

import ast
import importlib.util
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_normal_startup_has_no_harness_import_overrides_or_test_routes():
    check = """
import json, sys
from app.main import app
from app.auth.dependencies import get_token_verifier
print(json.dumps({
    'overrides': len(app.dependency_overrides),
    'harness_loaded': any('e2e_app' in name for name in sys.modules),
    'paths': list(app.openapi()['paths']),
    'verifier': type(get_token_verifier()).__name__,
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", check], cwd=ROOT, capture_output=True, text=True, check=True
    )
    facts = json.loads(result.stdout)
    assert facts["overrides"] == 0
    assert facts["harness_loaded"] is False
    assert facts["verifier"] in {"SupabaseTokenVerifier", "UnavailableTokenVerifier"}
    assert all("_e2e" not in path and "/test/" not in path for path in facts["paths"])
    assert "/api/auth/me" in facts["paths"]


def test_production_source_has_no_harness_import_or_auth_bypass_controls():
    forbidden = {
        "TEST_USER",
        "BYPASS_AUTH",
        "DISABLE_AUTH",
        "MASTER_TOKEN",
        "synthetic-publishable-placeholder",
        "browser-fixture",
    }
    for path in (ROOT / "app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all("e2e_app" not in alias.name for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                assert "e2e_app" not in (node.module or "")
            if isinstance(node, ast.Name):
                assert node.id not in forbidden
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value not in forbidden


@pytest.mark.anyio
async def test_harness_is_separate_and_accepts_only_current_random_test_token():
    from app.main import app as production

    before = production.dependency_overrides.copy()
    paths = set(production.openapi()["paths"])
    spec = importlib.util.spec_from_file_location(
        "isolated_browser_harness", ROOT / "tests/e2e_app.py"
    )
    assert spec and spec.loader
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    assert harness.app is not production
    assert production.dependency_overrides == before
    assert set(production.openapi()["paths"]) == paths
    assert all("_e2e" not in path for path in paths)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=harness.app), base_url="http://127.0.0.1"
    ) as client:
        token = str(uuid4())
        assert (await client.post("/_e2e/reset", json={"token": token})).status_code == 200
        assert (await client.get("/api/auth/me")).status_code == 401
        assert (
            await client.get("/api/auth/me", headers={"Authorization": f"Bearer {uuid4()}"})
        ).status_code == 401
        assert (
            await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        ).status_code == 200
        headers = {"Authorization": f"Bearer {token}"}
        foreign = f"/api/admin/workspaces/{harness.BETA}/conversations/{harness.CONV}"
        assert (await client.get(foreign, headers=headers)).status_code == 404
        assert (
            await client.post("/_e2e/reset", json={"token": token, "role": "member"})
        ).status_code == 200
        assert (
            await client.get(f"/api/admin/workspaces/{harness.ALPHA}/dashboard", headers=headers)
        ).status_code == 403
        assert (await client.post("/_e2e/reset", json={"token": str(uuid4())})).status_code == 200
        assert (
            await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        ).status_code == 401


@pytest.mark.anyio
async def test_harness_keeps_overlapping_customer_sessions_valid_until_reset():
    spec = importlib.util.spec_from_file_location(
        "isolated_browser_session_harness", ROOT / "tests/e2e_app.py"
    )
    assert spec and spec.loader
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    gateway = harness.CustomerGateway()
    first_hash = "a" * 64
    second_hash = "b" * 64

    expires_at = datetime.now(UTC)
    first = await gateway.create_session(UUID(harness.PUBLIC), first_hash, expires_at)
    second = await gateway.create_session(UUID(harness.PUBLIC), second_hash, expires_at)

    gateway.authorize(first.conversation_id, first_hash)
    gateway.authorize(second.conversation_id, second_hash)
    harness.state.reset(harness.Reset(token=str(uuid4())))
    with pytest.raises(harness.CustomerChatGatewayError):
        gateway.authorize(first.conversation_id, first_hash)
