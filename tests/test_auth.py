"""Blocco 6 — owner login. With VOICE_ORCH_OWNER_PASSWORD set, visitors can
read everything and use the demo features (voice test, knowledge preview,
try-it on FakeProvider), and nothing else can change without the owner's
session cookie. Unset, nothing changes (the rest of the suite runs that way).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import configure_test_db
from voice_orchestrator import config
from voice_orchestrator.webapi import auth
from voice_orchestrator.webapi.app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICE_ORCH_OWNER_PASSWORD", "segreta")
    monkeypatch.setattr(config, "CALL_LOG_FILE", tmp_path / "calls.jsonl")
    monkeypatch.setattr(config, "WEBHOOK_LOG_FILE", tmp_path / "wh.jsonl")
    monkeypatch.setattr(config, "PROVIDER", "fake")
    configure_test_db(tmp_path, monkeypatch, "auth.db")
    with TestClient(app) as c:
        yield c


def _login(client, password="segreta"):
    return client.post("/api/auth/login", json={"password": password})


def test_visitor_reads_but_cannot_write(client):
    assert client.get("/api/auth/me").json() == {"auth_required": True, "owner": False}
    assert client.get("/api/agents").status_code == 200
    assert client.get("/api/knowledge").status_code == 200
    for method, path, body in [
        ("post", "/api/agents", {"id": "x", "parent_id": "router", "name": "X"}),
        ("put", "/api/analysis/config", {"criteria": [], "data_items": []}),
        ("post", "/api/knowledge", {"name": "a", "content": "## a\nb"}),
        ("delete", "/api/knowledge/billing_policy.md", None),
        ("post", "/api/mcp-servers", {"name": "x", "command": "echo"}),
        ("post", "/api/agents/export", None),
        ("post", "/api/calls/whatever/analyze", None),
    ]:
        r = getattr(client, method)(path, **({"json": body} if body is not None else {}))
        assert r.status_code == 401, (method, path, r.status_code)


def test_visitor_demo_features_stay_open_and_free(client, monkeypatch):
    from voice_orchestrator.webapi import app as app_module

    monkeypatch.setattr(app_module, "get_provider", lambda *a, **k: pytest.fail("visitor reached the paid provider"))
    r = client.post("/api/test/route", json={"utterance": "il wifi non va", "use_configured_provider": True})
    assert r.status_code == 200 and r.json()["provider"] == "FakeProvider"
    assert client.post("/api/knowledge/search", json={"query": "router"}).status_code == 200
    assert client.post("/api/voice/token").status_code == 400  # open to visitors; 400 only for missing LiveKit keys here


def test_wrong_password_then_owner_session(client):
    assert _login(client, "sbagliata").status_code == 401
    r = _login(client)
    assert r.status_code == 200 and auth.COOKIE_NAME in r.cookies
    assert client.get("/api/auth/me").json()["owner"] is True
    assert client.post("/api/agents", json={"id": "nuovo", "parent_id": "router", "name": "N"}).status_code == 201

    client.post("/api/auth/logout")
    client.cookies.clear()
    assert client.post("/api/agents", json={"id": "altro", "parent_id": "router", "name": "A"}).status_code == 401


def test_tokens_expire_and_die_with_a_password_change(monkeypatch):
    monkeypatch.setenv("VOICE_ORCH_OWNER_PASSWORD", "uno")
    token = auth.make_token(now=1000)
    assert auth.token_valid(token, now=1000 + 60)
    assert not auth.token_valid(token, now=1000 + auth.SESSION_SECONDS + 1)
    assert not auth.token_valid(token.replace(".", ".0"), now=1001)
    monkeypatch.setenv("VOICE_ORCH_OWNER_PASSWORD", "due")
    assert not auth.token_valid(token, now=1001)


def test_no_password_means_no_login(tmp_path, monkeypatch):
    monkeypatch.delenv("VOICE_ORCH_OWNER_PASSWORD", raising=False)
    configure_test_db(tmp_path, monkeypatch, "open.db")
    with TestClient(app) as c:
        assert c.get("/api/auth/me").json() == {"auth_required": False, "owner": True}
        assert c.post("/api/agents", json={"id": "y", "parent_id": "router", "name": "Y"}).status_code == 201
