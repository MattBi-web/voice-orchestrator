"""Blocco 7, fase B — multi-turn text tests: the session carries over between
turns (handover, then the specialist answers the follow-up), slots can be
set mid-conversation, end_call ends it, and the conversation lands in the
call log once, as a route_test."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import configure_test_db
from voice_orchestrator import config
from voice_orchestrator.webapi import test_conversations
from voice_orchestrator.webapi.app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    configure_test_db(tmp_path, monkeypatch, "conv_agents.db")
    monkeypatch.setattr(config, "CALL_LOG_FILE", tmp_path / "conv_call_log.jsonl")
    monkeypatch.setattr(config, "WEBHOOK_LOG_FILE", tmp_path / "conv_webhook_log.jsonl")
    monkeypatch.setattr(config, "PROVIDER", "fake")
    test_conversations.reset_for_tests()
    with TestClient(app) as c:
        yield c
    test_conversations.reset_for_tests()


def _say(client, cid, text, **slots):
    r = client.post(f"/api/test/conversations/{cid}/turns", json={"utterance": text, "slots": slots})
    assert r.status_code == 200, r.text
    return r.json()


def test_conversation_keeps_the_specialist_and_ends_with_end_call(client):
    r = client.post("/api/test/conversations", json={})
    assert r.status_code == 201
    body = r.json()
    assert body["greeting"]["agent_id"] == "router" and body["simulated"] is True
    cid = body["id"]

    first = _say(client, cid, "Quanto costa il roaming in Francia?")
    assert first["agent_id"] == "roaming" and first["handed_off"] is True and first["seq"] == 1
    assert first["keyword"] == "roaming" and first["ended"] is False

    second = _say(client, cid, "e in Spagna?")
    assert second["from_agent_id"] == "roaming" and second["agent_id"] == "roaming" and second["seq"] == 2

    assert client.get("/api/calls").json()["calls"] == []  # logged only when it ends
    bye = _say(client, cid, "Perfetto, arrivederci")
    assert bye["tools"] == ["end_call"] and bye["ended"] is True

    calls = client.get("/api/calls").json()["calls"]
    assert len(calls) == 1 and calls[0]["source"] == "route_test" and calls[0]["turn_count"] >= 3
    assert client.post(f"/api/test/conversations/{cid}/turns", json={"utterance": "pronto?"}).status_code == 404


def test_verifying_the_caller_mid_conversation_opens_billing(client):
    cid = client.post("/api/test/conversations", json={}).json()["id"]
    closed = _say(client, cid, "Ho un problema con la bolletta")
    assert "billing" not in closed["eligible"] and closed["agent_id"] != "billing"
    opened = _say(client, cid, "Ho un problema con la bolletta", authenticated=True)
    assert opened["agent_id"] == "billing" and opened["resolved_by"] == "pattern"


def test_start_from_a_specialist_and_reset(client):
    r = client.post("/api/test/conversations", json={"start_agent_id": "tech_internet"})
    cid = r.json()["id"]
    turn = _say(client, cid, "il wifi non si connette")
    assert turn["from_agent_id"] == "tech_internet"
    assert client.delete(f"/api/test/conversations/{cid}").status_code == 204
    assert len(client.get("/api/calls").json()["calls"]) == 1
    assert client.post("/api/test/conversations", json={"start_agent_id": "nope"}).status_code == 404


def test_an_agent_deleted_mid_conversation_does_not_break_the_next_turn(client):
    cid = client.post("/api/test/conversations", json={}).json()["id"]
    assert _say(client, cid, "Quanto costa il roaming in Francia?")["agent_id"] == "roaming"
    assert client.delete("/api/agents/roaming").status_code in (200, 204)
    after = _say(client, cid, "ciao")
    assert after["seq"] == 2 and after["from_agent_id"] == "router"


def test_limits(client, monkeypatch):
    monkeypatch.setattr(test_conversations, "MAX_TURNS", 1)
    cid = client.post("/api/test/conversations", json={}).json()["id"]
    _say(client, cid, "ciao")
    assert client.post(f"/api/test/conversations/{cid}/turns", json={"utterance": "ancora"}).status_code == 429
    monkeypatch.setattr(test_conversations, "MAX_LIVE", 1)
    assert client.post("/api/test/conversations", json={}).status_code == 429
