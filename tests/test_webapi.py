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
    # Same isolation for blocco 3's webhook execution log.
    monkeypatch.setattr(config, "WEBHOOK_LOG_FILE", tmp_path / "test_webhook_log.jsonl")
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


def test_create_and_update_round_trip_blocco2_fields(client):
    """first_message/llm_*/voice_* (blocco 2) survive a create, a GET, and
    an update — the same round-trip test_create_get_update_delete_roundtrip
    already does for the pre-existing fields, just for the new ones."""
    created = client.post(
        "/api/agents",
        json={
            "id": "vip_support",
            "parent_id": "sales",
            "name": "VIP Escalations",
            "first_message": "Buongiorno, sono l'assistenza VIP.",
            "llm_provider": "fake",
            "llm_model": "",
            "llm_temperature": 0.3,
            "voice_id": "it-female-1",
            "voice_stability": 0.6,
            "voice_speed": 1.1,
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["first_message"] == "Buongiorno, sono l'assistenza VIP."
    assert body["llm_provider"] == "fake"
    assert body["llm_temperature"] == 0.3
    assert body["voice_id"] == "it-female-1"
    assert body["voice_stability"] == 0.6
    assert body["voice_speed"] == 1.1
    assert body["layout_x"] is None and body["layout_y"] is None

    updated = client.put(
        "/api/agents/vip_support",
        json={"name": "VIP Escalations", "llm_provider": "", "voice_id": "", "llm_temperature": None},
    )
    assert updated.status_code == 200
    assert updated.json()["llm_provider"] == ""
    assert updated.json()["voice_id"] == ""
    assert updated.json()["llm_temperature"] is None


def test_agent_layout_patch_persists_position_without_touching_other_fields(client):
    before = client.get("/api/agents/billing").json()

    patched = client.patch("/api/agents/billing/layout", json={"layout_x": 120.5, "layout_y": -30.0})
    assert patched.status_code == 200
    assert patched.json()["layout_x"] == 120.5
    assert patched.json()["layout_y"] == -30.0
    assert patched.json()["name"] == before["name"]
    assert patched.json()["system_prompt"] == before["system_prompt"]

    refetched = client.get("/api/agents/billing").json()
    assert refetched["layout_x"] == 120.5


def test_agent_layout_patch_unknown_agent_is_404(client):
    r = client.patch("/api/agents/does_not_exist/layout", json={"layout_x": 1, "layout_y": 1})
    assert r.status_code == 404


def test_reparent_moves_an_agent_and_keeps_its_own_fields(client):
    """D13 — dropping a node onto another one in the graph view."""
    before = client.get("/api/agents/billing").json()

    r = client.patch("/api/agents/billing/parent", json={"parent_id": "sales"})
    assert r.status_code == 200
    assert r.json()["parent_id"] == "sales"
    assert r.json()["name"] == before["name"]
    assert r.json()["system_prompt"] == before["system_prompt"]

    tree = client.get("/api/agents").json()
    sales = next(c for c in tree["root"]["children"] if c["id"] == "sales")
    assert "billing" in {c["id"] for c in sales["children"]}
    assert "billing" not in {c["id"] for c in tree["root"]["children"]}


def test_reparent_a_subtree_moves_the_whole_subtree_with_it(client):
    r = client.patch("/api/agents/tech_support/parent", json={"parent_id": "billing"})
    assert r.status_code == 200

    billing = client.get("/api/agents/billing").json()
    assert "tech_support" in billing["children_ids"]
    tech_support = client.get("/api/agents/tech_support").json()
    assert {"tech_internet", "tech_tv"} <= set(tech_support["children_ids"])


def test_reparent_onto_own_descendant_is_rejected_as_a_cycle(client):
    r = client.patch("/api/agents/tech_support/parent", json={"parent_id": "tech_internet"})
    assert r.status_code == 409


def test_reparent_onto_self_is_rejected_as_a_cycle(client):
    r = client.patch("/api/agents/tech_support/parent", json={"parent_id": "tech_support"})
    assert r.status_code == 409


def test_reparent_root_is_rejected(client):
    r = client.patch("/api/agents/router/parent", json={"parent_id": "billing"})
    assert r.status_code == 400


def test_reparent_onto_unknown_parent_is_400(client):
    r = client.patch("/api/agents/billing/parent", json={"parent_id": "does_not_exist"})
    assert r.status_code == 400


def test_reparent_unknown_agent_is_404(client):
    r = client.patch("/api/agents/does_not_exist/parent", json={"parent_id": "billing"})
    assert r.status_code == 404


def test_reparent_onto_current_parent_is_a_harmless_no_op(client):
    r = client.patch("/api/agents/billing/parent", json={"parent_id": "router"})
    assert r.status_code == 200
    assert r.json()["parent_id"] == "router"


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


def test_webhook_tools_auto_seeds_the_bundled_demo_entry(client):
    """config/webhook_tools.yaml ships with one "network_status" entry —
    same auto-seed-on-first-request behaviour as /api/mcp-servers."""
    tools = client.get("/api/webhook-tools").json()["tools"]
    assert [t["name"] for t in tools] == ["network_status"]
    assert tools[0]["url"] == "https://httpbin.org/anything"
    assert tools[0]["method"] == "POST"
    assert tools[0]["params"] == [{"name": "line_id", "source": "slot", "value": "account_number", "type": "string"}]


def test_webhook_tool_create_makes_it_usable_without_a_restart(client):
    """The whole point of webhook_sync.py: a tool created through the API
    must appear in tools.REGISTRY (via GET /api/tools) in the very same
    process, with zero restart — not just present in a later GET of its own
    list. No live HTTP call here on purpose — webapi tests stay offline."""
    created = client.post(
        "/api/webhook-tools",
        json={
            "name": "order_status",
            "description": "Looks up an order.",
            "url": "https://example.test/orders",
            "method": "GET",
            "headers": {"Authorization": "{{secret:ORDERS_API_KEY}}"},
            "params": [{"name": "order_id", "source": "slot", "value": "order_id", "type": "string"}],
            "triggers": ["dov'è il mio ordine"],
            "timeout_seconds": 3,
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "order_status"
    assert body["headers"] == {"Authorization": "{{secret:ORDERS_API_KEY}}"}  # stored as-written, never resolved here
    assert body["params"][0]["value"] == "order_id"

    assert "webhook:order_status" in client.get("/api/tools").json()["tools"]


def test_webhook_tool_create_rejects_duplicate_name(client):
    r = client.post("/api/webhook-tools", json={"name": "network_status", "url": "https://x.test"})
    assert r.status_code == 409


def test_webhook_tool_update_roundtrip(client):
    updated = client.put(
        "/api/webhook-tools/network_status",
        json={"name": "network_status", "url": "https://example.test/status", "method": "GET", "timeout_seconds": 2},
    )
    assert updated.status_code == 200
    assert updated.json()["url"] == "https://example.test/status"
    assert updated.json()["method"] == "GET"
    assert updated.json()["timeout_seconds"] == 2


def test_webhook_tool_update_unknown_is_404(client):
    r = client.put("/api/webhook-tools/does_not_exist", json={"name": "does_not_exist", "url": "https://x.test"})
    assert r.status_code == 404


def test_webhook_tool_delete_blocked_while_an_agent_still_uses_it(client):
    """config/agents.yaml's "tech_internet" agent has tools: [...,
    "webhook:network_status", ...] — the seeded agents DB mirrors that, so
    deleting "network_status" out from under it would leave a dangling tool
    reference, same guard as the MCP server delete above."""
    r = client.delete("/api/webhook-tools/network_status")
    assert r.status_code == 409


def test_webhook_tool_delete_roundtrip_and_drops_from_registry(client):
    client.post("/api/webhook-tools", json={"name": "scratch", "url": "https://example.test/scratch"})
    assert "webhook:scratch" in client.get("/api/tools").json()["tools"]

    deleted = client.delete("/api/webhook-tools/scratch")
    assert deleted.status_code == 204
    assert "webhook:scratch" not in client.get("/api/tools").json()["tools"]
    assert [t["name"] for t in client.get("/api/webhook-tools").json()["tools"]] == ["network_status"]


def test_webhook_tool_delete_unknown_is_404(client):
    r = client.delete("/api/webhook-tools/does_not_exist")
    assert r.status_code == 404


def test_webhook_executions_empty_log_is_an_empty_list(client):
    assert client.get("/api/webhook-tools/executions").json() == {"executions": []}


def test_webhook_executions_reads_back_logged_calls_newest_first(client):
    from voice_orchestrator.tools import webhook_log

    webhook_log.append(
        webhook_log.Execution(
            tool_name="network_status", call_id="c1", agent_id="tech_internet",
            url="https://httpbin.org/anything", method="POST", ok=True, status_code=200, latency_ms=12.3,
        )
    )
    webhook_log.append(
        webhook_log.Execution(
            tool_name="network_status", call_id="c2", agent_id="tech_internet",
            url="https://httpbin.org/anything", method="POST", ok=False, status_code=500, latency_ms=8.1,
            error="server error",
        )
    )
    executions = client.get("/api/webhook-tools/executions").json()["executions"]
    assert [e["call_id"] for e in executions] == ["c2", "c1"]
    assert executions[0]["ok"] is False
    assert executions[0]["error"] == "server error"


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
    assert [c["id"] for c in config_body["criteria"]] == ["richiesta_risolta", "agente_corretto", "senza_operatore"]
    kinds = {c["id"]: (c["kind"], c["expected"]) for c in config_body["criteria"]}
    assert kinds["senza_operatore"] == ("tool_not_used", ["transfer_to_human"])
    assert {d["id"] for d in config_body["data_items"]} == {"motivo_chiamata", "richiesta_operatore"}


def test_analyze_stores_result_and_feeds_list_and_stats(client):
    call_id = _one_call(client)
    result = client.post(f"/api/calls/{call_id}/analyze").json()

    assert result["method"] == "heuristic"  # no API key in tests
    assert result["call_successful"] in ("success", "failure", "unknown")
    assert {c["criterion_id"] for c in result["criteria"]} == {"richiesta_risolta", "agente_corretto", "senza_operatore"}
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


def test_export_writes_the_builder_family_to_agents_yaml(client, tmp_path, monkeypatch):
    """Must never touch the real repo config/agents.yaml in a test run — point
    config.AGENTS_FILE at a throwaway path first, same as CALL_LOG_FILE/the
    DB above are redirected in the fixture."""
    export_path = tmp_path / "exported_agents.yaml"
    monkeypatch.setattr(config, "AGENTS_FILE", export_path)

    client.post("/api/agents", json={"id": "vip", "parent_id": "sales", "name": "VIP", "triggers": ["vip"]})

    r = client.post("/api/agents/export")
    assert r.status_code == 200
    body = r.json()
    assert body["path"] == str(export_path)
    assert body["agent_count"] >= 6  # router + the 4 demo agents + the new one

    from voice_orchestrator.agents.registry import load_family

    exported = load_family(export_path)
    assert exported.find("vip") is not None
    assert exported.find("vip").triggers == ["vip"]


# ---- D3: try-it box on the configured provider ----


def test_llm_status_reports_fake_by_default(client):
    assert client.get("/api/llm/status").json() == {"requested": "fake", "resolved": "FakeProvider", "real": False}


def test_test_route_defaults_to_fake_provider(client):
    body = client.post("/api/test/route", json={"utterance": "il wifi non si connette"}).json()
    assert body["provider"] == "FakeProvider"


def test_test_route_can_use_the_configured_provider(client, monkeypatch):
    from voice_orchestrator import llm
    from voice_orchestrator.webapi import app as app_module

    class Configured(llm.FakeProvider):
        def respond(self, *args, **kwargs):
            return "risposta dal provider configurato"

    monkeypatch.setattr(app_module, "get_provider", lambda *a, **k: Configured())
    body = client.post(
        "/api/test/route", json={"utterance": "il wifi non si connette", "use_configured_provider": True}
    ).json()
    assert body["reply"] == "risposta dal provider configurato"
    assert body["provider"] == "Configured"


def test_test_route_provider_error_is_a_502(client, monkeypatch):
    from voice_orchestrator import llm
    from voice_orchestrator.webapi import app as app_module

    class Broken(llm.LLMProvider):
        def classify(self, *a, **k):
            raise RuntimeError("invalid x-api-key")

        def respond(self, *a, **k):
            raise RuntimeError("invalid x-api-key")

        def summarize(self, *a, **k):
            return ""

    monkeypatch.setattr(app_module, "get_provider", lambda *a, **k: Broken())
    r = client.post("/api/test/route", json={"utterance": "zzz", "use_configured_provider": True})
    assert r.status_code == 502
    assert "invalid x-api-key" in r.json()["detail"]


# ---- D11: criterion kinds through the API ----


def test_put_analysis_config_round_trips_kinds_and_validates_them(client):
    body = {
        "criteria": [
            {"id": "fine", "name": "Fine", "kind": "final_agent", "expected": ["roaming"]},
            {"id": "llm", "name": "LLM", "prompt": "Il chiamante è soddisfatto."},
        ],
        "data_items": [],
    }
    r = client.put("/api/analysis/config", json=body)
    assert r.status_code == 200
    got = {c["id"]: c for c in r.json()["criteria"]}
    assert got["fine"]["kind"] == "final_agent" and got["fine"]["expected"] == ["roaming"]
    assert got["llm"]["kind"] == "llm"

    no_tool = {"criteria": [{"id": "t", "kind": "tool_used", "expected": []}], "data_items": []}
    assert client.put("/api/analysis/config", json=no_tool).status_code == 400
    no_prompt = {"criteria": [{"id": "p", "kind": "llm", "prompt": " "}], "data_items": []}
    assert client.put("/api/analysis/config", json=no_prompt).status_code == 400


def test_sync_columns_upgrades_a_pre_blocco_2_database(tmp_path):
    """A DB created by an older model: `agents` lacks every blocco 2/4
    column and still has the NOT NULL `voice` column the model dropped;
    `evaluation_criteria` lacks D11's columns. Opening it must add what's
    missing and drop the column that would break every INSERT."""
    import sqlite3

    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE agents (id VARCHAR NOT NULL, parent_id VARCHAR, name VARCHAR NOT NULL,
            description VARCHAR NOT NULL, system_prompt VARCHAR NOT NULL, eligibility VARCHAR NOT NULL,
            voice VARCHAR NOT NULL, position INTEGER NOT NULL, triggers_json TEXT NOT NULL,
            tools_json TEXT NOT NULL, knowledge_json TEXT NOT NULL, PRIMARY KEY (id),
            FOREIGN KEY(parent_id) REFERENCES agents (id));
        CREATE TABLE evaluation_criteria (id VARCHAR NOT NULL, name VARCHAR NOT NULL,
            prompt TEXT NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (id));
        INSERT INTO evaluation_criteria VALUES ('vecchio', 'Vecchio', 'prompt', 0);
        """
    )
    con.commit()
    con.close()

    engine = db.make_engine(path)
    cols = {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(agents)")}
    assert {"first_message", "llm_provider", "voice_id", "layout_x"} <= cols
    assert "voice" not in cols
    crit = sqlite3.connect(path).execute("SELECT kind, expected_json FROM evaluation_criteria").fetchall()
    assert crit == [("llm", "[]")]
    assert db.sync_columns(engine) == []  # idempotent
