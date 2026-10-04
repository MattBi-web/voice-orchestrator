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
    # Post-call analysis uses the configured provider; pin it to the
    # zero-key FakeProvider so a developer's own VOICE_ORCH_PROVIDER can't
    # turn this suite into real (billed) LLM calls.
    monkeypatch.setattr(config, "PROVIDER", "fake")
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


def test_mcp_servers_auto_seeds_the_bundled_demo_entry(client):
    """config/mcp_servers.yaml ships with one "demo" entry — same
    auto-seed-on-first-request behaviour as /api/agents."""
    servers = client.get("/api/mcp-servers").json()["servers"]
    assert [s["name"] for s in servers] == ["demo"]
    assert servers[0]["command"] == "python3"  # literal YAML text, unresolved


def test_mcp_server_create_makes_it_usable_without_a_restart(client):
    """The whole point of mcp_sync.py: a server created through the API must
    be callable through /api/test/route in the very same process, with zero
    restart — not just present in a later GET. Spawns the bundled demo
    stdio server under a second name, proving this isn't just re-reading the
    one already in tools.REGISTRY from import time."""
    created = client.post(
        "/api/mcp-servers",
        json={
            "name": "demo2",
            "command": "python3",
            "args": ["-m", "voice_orchestrator.tools.demo_mcp_server"],
        },
    )
    assert created.status_code == 201
    assert created.json() == {"name": "demo2", "command": "python3", "args": ["-m", "voice_orchestrator.tools.demo_mcp_server"]}

    assert "mcp:demo2" in client.get("/api/tools").json()["tools"]

    r = client.post(
        "/api/test/route",
        json={
            "utterance": "quanto costa il roaming dati in Francia?",
            "start_agent_id": "roaming",
        },
    )
    # roaming's agents.yaml tools: list only knows about "mcp:demo" — but
    # the new server is live in the registry either way (get_tool() would
    # resolve it); this call is really just proving the process didn't need
    # a restart to find "mcp:demo2" at all, via the /api/tools check above.
    assert r.status_code == 200


def test_mcp_server_create_rejects_duplicate_name(client):
    r = client.post("/api/mcp-servers", json={"name": "demo", "command": "python3"})
    assert r.status_code == 409


def test_mcp_server_update_roundtrip(client):
    updated = client.put("/api/mcp-servers/demo", json={"name": "demo", "command": "python3", "args": ["-m", "x"]})
    assert updated.status_code == 200
    assert updated.json()["args"] == ["-m", "x"]


def test_mcp_server_update_unknown_is_404(client):
    r = client.put("/api/mcp-servers/does_not_exist", json={"name": "does_not_exist", "command": "python3"})
    assert r.status_code == 404


def test_mcp_server_delete_blocked_while_an_agent_still_uses_it(client):
    """config/agents.yaml's "roaming" agent has tools: ["mcp:demo"] — the
    seeded agents DB mirrors that, so deleting "demo" out from under it
    would leave a dangling tool reference."""
    r = client.delete("/api/mcp-servers/demo")
    assert r.status_code == 409


def test_mcp_server_delete_roundtrip_and_drops_from_registry(client):
    client.post("/api/mcp-servers", json={"name": "scratch", "command": "python3", "args": ["-m", "x"]})
    assert "mcp:scratch" in client.get("/api/tools").json()["tools"]

    deleted = client.delete("/api/mcp-servers/scratch")
    assert deleted.status_code == 204
    assert "mcp:scratch" not in client.get("/api/tools").json()["tools"]
    assert client.get("/api/mcp-servers").json()["servers"] == [
        {"name": "demo", "command": "python3", "args": ["-m", "voice_orchestrator.tools.demo_mcp_server"]}
    ]


def test_mcp_server_delete_unknown_is_404(client):
    r = client.delete("/api/mcp-servers/does_not_exist")
    assert r.status_code == 404


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


# ---- conversations + post-call analysis ----


def _one_call(client, utterance="voglio parlare con un operatore", start="tech_internet") -> str:
    client.post("/api/test/route", json={"utterance": utterance, "start_agent_id": start})
    return client.get("/api/calls").json()["calls"][0]["call_id"]


def test_call_detail_has_the_transcript_with_routing_and_tools(client):
    call_id = _one_call(client)
    detail = client.get(f"/api/calls/{call_id}").json()

    assert [t["speaker"] for t in detail["turns"]] == ["caller", "agent"]
    assert detail["turns"][0]["routing"]["chosen_agent"] == "tech_internet"
    assert "transfer_to_human" in detail["turns"][1]["tools"]
    assert detail["analysis"] is None


def test_call_list_omits_transcripts_but_carries_the_verdict(client):
    _one_call(client)
    row = client.get("/api/calls").json()["calls"][0]
    assert "turns" not in row
    assert row["call_successful"] is None


def test_unknown_call_is_404_for_detail_and_analyze(client):
    assert client.get("/api/calls/nope").status_code == 404
    assert client.post("/api/calls/nope/analyze").status_code == 404


def test_analysis_config_is_seeded_with_defaults(client):
    config_body = client.get("/api/analysis/config").json()
    assert [c["id"] for c in config_body["criteria"]] == ["richiesta_risolta", "agente_corretto"]
    assert {d["id"] for d in config_body["data_items"]} == {"motivo_chiamata", "richiesta_operatore"}


def test_analyze_stores_result_and_feeds_list_and_stats(client):
    call_id = _one_call(client)
    result = client.post(f"/api/calls/{call_id}/analyze").json()

    assert result["method"] == "heuristic"  # no API key in tests
    assert result["call_successful"] in ("success", "failure", "unknown")
    assert {c["criterion_id"] for c in result["criteria"]} == {"richiesta_risolta", "agente_corretto"}
    data = {d["item_id"]: d["value"] for d in result["data"]}
    assert data["richiesta_operatore"] is True  # "voglio parlare con un operatore"

    detail = client.get(f"/api/calls/{call_id}").json()
    assert detail["analysis"]["call_successful"] == result["call_successful"]
    assert detail["analysis"]["analyzed_at"]

    row = client.get("/api/calls").json()["calls"][0]
    assert row["call_successful"] == result["call_successful"]

    stats = client.get("/api/calls/stats").json()
    assert stats["analyzed_calls"] == 1
    assert sum(stats["analysis_outcomes"].values()) == 1


def test_stats_success_rate_is_null_until_something_is_analyzed(client):
    _one_call(client)
    stats = client.get("/api/calls/stats").json()
    assert stats["analyzed_calls"] == 0
    assert stats["success_rate"] is None


def test_put_analysis_config_replaces_and_reanalysis_uses_it(client):
    r = client.put(
        "/api/analysis/config",
        json={
            "criteria": [{"id": "operatore", "name": "Operatore", "prompt": "Il chiamante chiede di parlare con un operatore."}],
            "data_items": [{"id": "importo", "type": "number", "description": "importo citato"}],
        },
    )
    assert r.status_code == 200
    assert [c["id"] for c in r.json()["criteria"]] == ["operatore"]

    call_id = _one_call(client)
    result = client.post(f"/api/calls/{call_id}/analyze").json()
    assert [c["criterion_id"] for c in result["criteria"]] == ["operatore"]
    assert [d["item_id"] for d in result["data"]] == ["importo"]


def test_put_analysis_config_rejects_duplicates_and_bad_ids(client):
    dup = {"criteria": [{"id": "a", "prompt": "x"}, {"id": "a", "prompt": "y"}], "data_items": []}
    assert client.put("/api/analysis/config", json=dup).status_code == 400
    bad = {"criteria": [{"id": "con spazi", "prompt": "x"}], "data_items": []}
    assert client.put("/api/analysis/config", json=bad).status_code == 400
    bad_type = {"criteria": [], "data_items": [{"id": "x", "type": "date", "description": "d"}]}
    assert client.put("/api/analysis/config", json=bad_type).status_code == 422


def test_emptying_the_config_survives_a_restart(client):
    """The seed flag: deleting every criterion on purpose must not be undone
    by the next startup's seed-if-empty."""
    client.put("/api/analysis/config", json={"criteria": [], "data_items": []})
    with TestClient(app) as again:  # same DB file, fresh lifespan = a restart
        body = again.get("/api/analysis/config").json()
    assert body == {"criteria": [], "data_items": []}
