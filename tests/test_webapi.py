"""Tests for the agent-builder FastAPI backend. Each test gets its own
throwaway SQLite file (via `db.configure()`) so nothing here touches
`data/agents.db`, the file a developer running the web UI locally actually
uses — and so tests can run in any order without seeing each other's data.
"""
from __future__ import annotations

import jwt
import pytest
from fastapi.testclient import TestClient

from voice_orchestrator import config
from voice_orchestrator.webapi import db
from voice_orchestrator.webapi.app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    db.configure(tmp_path / "test_agents.db")
    # Every test gets its own throwaway call log too, for the same reason:
    # nothing here should touch a developer's real data/call_log.jsonl, and
    # tests must not see each other's logged calls.
    monkeypatch.setattr(config, "CALL_LOG_FILE", tmp_path / "test_call_log.jsonl")
    with TestClient(app) as c:
        yield c


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_agents_tree_auto_seeds_from_yaml_on_first_request(client):
    body = client.get("/api/agents").json()
    assert body["root"]["id"] == "router"
    child_ids = {c["id"] for c in body["root"]["children"]}
    assert {"billing", "sales", "roaming", "tech_support"} <= child_ids


def test_seed_is_not_repeated_on_a_second_request(client):
    """A real editing session must survive a server restart without the
    next startup silently reseeding over the user's edits."""
    first = client.get("/api/agents").json()
    client.delete("/api/agents/roaming")  # roaming has no children, safe to delete
    second = client.get("/api/agents").json()
    ids_after_delete = {c["id"] for c in second["root"]["children"]}
    assert "roaming" not in ids_after_delete
    assert len(first["root"]["children"]) == len(second["root"]["children"]) + 1


def test_tools_lists_the_real_registry(client):
    tools = client.get("/api/tools").json()["tools"]
    assert "transfer_to_human" in tools
    assert "knowledge_lookup" in tools


def test_create_get_update_delete_roundtrip(client):
    created = client.post(
        "/api/agents",
        json={
            "id": "vip_support",
            "parent_id": "sales",
            "name": "VIP Escalations",
            "description": "Handles VIP customer escalations",
            "triggers": ["vip", "escalation"],
            "tools": [{"id": "transfer_to_human"}],
        },
    )
    assert created.status_code == 201
    assert created.json()["parent_id"] == "sales"

    fetched = client.get("/api/agents/vip_support")
    assert fetched.status_code == 200
    assert fetched.json()["triggers"] == ["vip", "escalation"]

    updated = client.put(
        "/api/agents/vip_support",
        json={"name": "VIP Escalations (updated)", "tools": [{"id": "transfer_to_human", "condition": "channel == 'voice'"}]},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "VIP Escalations (updated)"
    assert updated.json()["tools"][0]["condition"] == "channel == 'voice'"

    deleted = client.delete("/api/agents/vip_support")
    assert deleted.status_code == 204
    assert client.get("/api/agents/vip_support").status_code == 404


def test_create_rejects_duplicate_id(client):
    r = client.post("/api/agents", json={"id": "billing", "parent_id": "router", "name": "dup"})
    assert r.status_code == 409


def test_create_rejects_missing_parent(client):
    r = client.post("/api/agents", json={"id": "orphan", "parent_id": "does_not_exist", "name": "x"})
    assert r.status_code == 400


def test_delete_blocks_on_root(client):
    r = client.delete("/api/agents/router")
    assert r.status_code == 400


def test_delete_blocks_when_agent_has_children(client):
    r = client.delete("/api/agents/tech_support")
    assert r.status_code == 409


def test_update_unknown_agent_is_404(client):
    r = client.put("/api/agents/does_not_exist", json={"name": "x"})
    assert r.status_code == 404


def test_test_route_runs_the_real_orchestrator(client):
    r = client.post("/api/test/route", json={"utterance": "quanto costa il roaming in Francia?"})
    assert r.status_code == 200
    body = r.json()
    assert body["agent_id"] == "roaming"
    assert "mcp:demo" in body["tool_ids_used"]
    assert body["reply"]


def test_test_route_can_start_from_a_specific_agent(client):
    r = client.post(
        "/api/test/route",
        json={"utterance": "voglio parlare con un operatore", "start_agent_id": "tech_internet"},
    )
    assert r.status_code == 200
    assert r.json()["agent_id"] == "tech_internet"
    assert "transfer_to_human" in r.json()["tool_ids_used"]


def test_test_route_unknown_start_agent_is_404(client):
    r = client.post("/api/test/route", json={"utterance": "ciao", "start_agent_id": "nope"})
    assert r.status_code == 404


def test_voice_status_reports_not_configured_by_default(client):
    """No LIVEKIT_* env vars in the test environment — the console should
    report itself as unavailable rather than letting a token request fail
    with an opaque error."""
    assert client.get("/api/voice/status").json() == {"configured": False}


def test_voice_token_without_credentials_is_400(client):
    r = client.post("/api/voice/token")
    assert r.status_code == 400


def test_test_route_logs_a_call_tagged_route_test(client):
    client.post("/api/test/route", json={"utterance": "il wifi non si connette"})

    calls = client.get("/api/calls").json()["calls"]
    assert len(calls) == 1
    assert calls[0]["source"] == "route_test"
    assert calls[0]["final_agent_id"] == "tech_support"


def test_calls_endpoint_filters_by_source_and_orders_newest_first(client):
    client.post("/api/test/route", json={"utterance": "il wifi non si connette"})
    client.post("/api/test/route", json={"utterance": "quanto costa il roaming in Francia?"})

    all_calls = client.get("/api/calls").json()["calls"]
    assert len(all_calls) == 2
    assert all_calls[0]["final_agent_id"] == "roaming"  # newest first

    filtered = client.get("/api/calls", params={"source": "chat"}).json()["calls"]
    assert filtered == []


def test_call_stats_aggregates_routing_and_tool_counts(client):
    client.post("/api/test/route", json={"utterance": "quanto costa il roaming in Francia?"})
    client.post("/api/test/route", json={"utterance": "voglio parlare con un operatore", "start_agent_id": "tech_internet"})

    stats = client.get("/api/calls/stats").json()
    assert stats["total_calls"] == 2
    assert stats["resolved_by_totals"]["pattern"] + stats["resolved_by_totals"]["gate_only"] >= 1
    assert "mcp:demo" in stats["tool_totals"]
    assert stats["calls_by_source"] == {"route_test": 2}
    assert len(stats["calls_by_day"]) == 14  # default window, zero-filled


def test_call_stats_can_exclude_route_test_calls(client):
    client.post("/api/test/route", json={"utterance": "ciao"})
    stats = client.get("/api/calls/stats", params={"include_test": "false"}).json()
    assert stats["total_calls"] == 0


def test_voice_token_with_credentials_mints_a_room_scoped_jwt(client, monkeypatch):
    monkeypatch.setattr(config, "LIVEKIT_URL", "wss://example.livekit.cloud")
    monkeypatch.setattr(config, "LIVEKIT_API_KEY", "APItest")
    monkeypatch.setattr(config, "LIVEKIT_API_SECRET", "s3cr3t-with-enough-length")
    assert client.get("/api/voice/status").json() == {"configured": True}

    r = client.post("/api/voice/token")
    assert r.status_code == 200
    body = r.json()
    assert body["url"] == "wss://example.livekit.cloud"
    assert body["room"].startswith("webtest-")

    # Decode for real (not just "is it a string") — proves the JWT actually
    # grants exactly the room/identity the response claims, the same shape
    # livekit-client in the browser will check.
    payload = jwt.decode(
        body["token"], "s3cr3t-with-enough-length", algorithms=["HS256"], options={"verify_aud": False}
    )
    assert payload["video"]["room"] == body["room"]
    assert payload["video"]["roomJoin"] is True
    assert payload["sub"] == body["identity"]
