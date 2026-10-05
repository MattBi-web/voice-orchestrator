"""Blocco 8 — projects: several phone lines, each a single agent or a
workflow, with default models per pipeline piece that every agent inherits
and can override. Covers the resolution rules (project.py), the API, the
catalog, per-project calls and voice rooms, and the migration of a
database from before projects."""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from conftest import configure_test_db
from voice_orchestrator import config, project
from voice_orchestrator.agents.registry import AgentSpec
from voice_orchestrator.project import ModelSettings
from voice_orchestrator.webapi import db, test_conversations
from voice_orchestrator.webapi.app import app
from voice_orchestrator.webapi.voice_token import project_from_room, room_name_for


@pytest.fixture
def client(tmp_path, monkeypatch):
    configure_test_db(tmp_path, monkeypatch, "projects.db")
    monkeypatch.setattr(config, "CALL_LOG_FILE", tmp_path / "calls.jsonl")
    monkeypatch.setattr(config, "WEBHOOK_LOG_FILE", tmp_path / "webhooks.jsonl")
    monkeypatch.setattr(config, "PROVIDER", "fake")
    test_conversations.reset_for_tests()
    with TestClient(app) as c:
        yield c


def _agent(**kw) -> AgentSpec:
    return AgentSpec(id="a", name="A", description="", **kw)


# ---- resolution (project.py) ----


def test_agents_inherit_the_project_models():
    s = ModelSettings(tts_provider="elevenlabs", tts_model="eleven_turbo_v2_5", voice_id="v1", llm_provider="anthropic", llm_model="m")
    steps = {p["component"]: p for p in project.pipeline(_agent(), s)}
    assert steps["tts"]["model"] == "eleven_turbo_v2_5" and steps["tts"]["voice_id"] == "v1"
    assert steps["tts"]["source"] == "project" and steps["llm"]["provider"] == "anthropic"
    assert steps["stt"]["provider"] == "deepgram" and steps["stt"]["language"] == "multi"
    assert steps["router"]["provider"] == "anthropic"  # no router model chosen: same as the agents' LLM


def test_a_field_override_keeps_the_rest_of_the_project_choice():
    s = ModelSettings(tts_model="eleven_turbo_v2_5", voice_id="v1")
    tts = project.tts_for(_agent(voice_id="v2"), s)
    assert (tts.provider, tts.model, tts.extra["voice_id"], tts.source) == ("elevenlabs", "eleven_turbo_v2_5", "v2", "agent")


def test_switching_provider_drops_the_project_model_and_voice():
    s = ModelSettings(tts_model="eleven_turbo_v2_5", voice_id="v1")
    tts = project.tts_for(_agent(tts_provider="openai"), s)
    assert (tts.provider, tts.model, tts.extra["voice_id"]) == ("openai", "", "")
    stt = project.stt_for(_agent(stt_provider="openai", stt_model="whisper-1"), s)
    assert (stt.provider, stt.model, stt.extra["language"]) == ("openai", "whisper-1", "")


def test_router_model_and_deployment_fallback(monkeypatch):
    monkeypatch.setattr(config, "PROVIDER", "fake")
    assert project.router_for(ModelSettings()).source == "deployment"
    r = project.router_for(ModelSettings(llm_provider="openai", llm_model="gpt-4.1", router_provider="anthropic", router_model="haiku"))
    assert (r.provider, r.model) == ("anthropic", "haiku")
    assert project.llm_for(_agent(), ModelSettings()).source == "deployment"


def test_visitor_responder_never_builds_a_real_provider(monkeypatch):
    monkeypatch.setattr(project, "cached_provider", lambda *a, **k: pytest.fail("built a real provider"))
    provider, _ = project.responder(ModelSettings(llm_provider="anthropic"), force_fake=True)(_agent(llm_provider="openai"))
    assert type(provider).__name__ == "FakeProvider"


# ---- API ----


def test_the_demo_is_the_first_project(client):
    projects = client.get("/api/projects").json()["projects"]
    assert [p["id"] for p in projects] == ["demo"]
    demo = projects[0]
    assert demo["name"] == "Meridian Telecom" and demo["kind"] == "workflow" and demo["agent_count"] == 7
    assert demo["settings"]["stt_provider"] == "deepgram" and demo["settings"]["tts_model"] == "eleven_flash_v2_5"


def test_create_single_and_workflow_from_templates(client):
    ids = {t["id"] for t in client.get("/api/templates").json()["templates"]}
    assert ids == {"single", "workflow", "demo"}

    single = client.post("/api/projects", json={"name": "Pizzeria Da Mario", "template": "single"}).json()
    assert single["id"] == "pizzeria-da-mario" and single["kind"] == "single" and single["agent_count"] == 1
    flow = client.post("/api/projects", json={"name": "Pizzeria Da Mario", "template": "workflow"}).json()
    assert flow["id"] == "pizzeria-da-mario-2" and flow["kind"] == "workflow"

    tree = client.get(f"/api/projects/{flow['id']}/agents").json()["root"]
    assert tree["id"] == "receptionist" and [c["id"] for c in tree["children"]] == ["sales", "support"]
    assert client.post("/api/projects", json={"name": "x", "template": "nope"}).status_code == 400
    assert client.post("/api/projects", json={"name": "  ", "template": "single"}).status_code == 400


def test_agent_ids_are_per_project_and_edits_stay_inside(client):
    copy = client.post("/api/projects", json={"name": "Copia", "template": "demo"}).json()["id"]
    agent = client.get(f"/api/projects/{copy}/agents/billing").json()
    agent["name"] = "Fatture"
    assert client.put(f"/api/projects/{copy}/agents/billing", json=agent).status_code == 200
    assert client.get("/api/agents/billing").json()["name"] == "Billing Agent"  # the demo is untouched

    r = client.post(f"/api/projects/{copy}/agents", json={"id": "vip", "parent_id": "sales", "name": "VIP"})
    assert r.status_code == 201
    assert client.get("/api/agents/vip").status_code == 404
    assert client.get("/api/projects/nope/agents").status_code == 404

    assert client.delete(f"/api/projects/{copy}").status_code == 204
    assert client.get(f"/api/projects/{copy}").status_code == 404
    assert client.get("/api/agents/billing").status_code == 200


def test_settings_overrides_and_pipeline(client):
    pid = client.post("/api/projects", json={"name": "Line", "template": "workflow"}).json()["id"]
    body = {"name": "Line", "description": "d", "settings": {"tts_provider": "elevenlabs", "voice_id": "v1", "llm_provider": "fake"}}
    assert client.put(f"/api/projects/{pid}", json=body).json()["settings"]["voice_id"] == "v1"

    agent = client.get(f"/api/projects/{pid}/agents/support").json()
    agent.update(tts_provider="openai", tts_model="gpt-4o-mini-tts", voice_id="coral", stt_language="it")
    client.put(f"/api/projects/{pid}/agents/support", json=agent)
    saved = client.get(f"/api/projects/{pid}/agents/support").json()
    assert (saved["tts_provider"], saved["stt_language"]) == ("openai", "it")

    steps = {s["component"]: s for s in client.get(f"/api/projects/{pid}/agents/support/pipeline").json()["steps"]}
    assert steps["tts"]["provider"] == "openai" and steps["tts"]["voice_id"] == "coral" and steps["tts"]["source"] == "agent"
    assert steps["stt"]["provider"] == "deepgram" and steps["stt"]["language"] == "it" and steps["stt"]["source"] == "agent"
    sales = {s["component"]: s for s in client.get(f"/api/projects/{pid}/agents/sales/pipeline").json()["steps"]}
    assert sales["tts"]["voice_id"] == "v1" and sales["tts"]["source"] == "project"

    exported = client.get(f"/api/projects/{pid}/export").json()
    assert "voice_id: v1" in exported["yaml"] and exported["json"]["root"]["id"] == "receptionist"


def test_catalog_marks_what_can_run(client, monkeypatch):
    monkeypatch.delenv("CARTESIA_API_KEY", raising=False)
    monkeypatch.setenv("DEEPGRAM_API_KEY", "x")
    cat = client.get("/api/catalog").json()
    deepgram = next(p for p in cat["stt"] if p["id"] == "deepgram")
    cartesia = next(p for p in cat["tts"] if p["id"] == "cartesia")
    assert deepgram["available"] is True and "nova-3" in deepgram["models"]
    assert cartesia["available"] is False and "CARTESIA_API_KEY" in cartesia["missing"]
    assert any(p["id"] == "fake" and p["available"] for p in cat["llm"])


def test_calls_and_tests_are_per_project(client):
    pid = client.post("/api/projects", json={"name": "Solo", "template": "single"}).json()["id"]
    cid = client.post("/api/test/conversations", json={"project_id": pid}).json()["id"]
    turn = client.post(f"/api/test/conversations/{cid}/turns", json={"utterance": "ciao, arrivederci"}).json()
    assert turn["agent_id"] == "assistant" and turn["ended"] is True
    client.post("/api/test/route", json={"utterance": "il wifi non va"})  # demo
    mine = client.get(f"/api/calls?project={pid}").json()["calls"]
    assert len(mine) == 1 and mine[0]["project_id"] == pid
    assert len(client.get("/api/calls?project=demo").json()["calls"]) == 1
    projects = {p["id"]: p for p in client.get("/api/projects").json()["projects"]}
    assert projects[pid]["call_count"] == 1


def test_voice_room_names_carry_the_project():
    room = room_name_for("pizzeria-da-mario")
    assert project_from_room(room) == "pizzeria-da-mario"
    assert project_from_room("d12-e2e-abc") is None


def test_a_database_from_before_projects_is_migrated(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE agents (id VARCHAR PRIMARY KEY, parent_id VARCHAR REFERENCES agents(id), name VARCHAR NOT NULL,"
        " description VARCHAR NOT NULL, system_prompt VARCHAR NOT NULL, eligibility VARCHAR NOT NULL,"
        " position INTEGER NOT NULL, triggers_json TEXT NOT NULL, tools_json TEXT NOT NULL, knowledge_json TEXT NOT NULL)"
    )
    con.execute("INSERT INTO agents VALUES ('root', NULL, 'Root', '', '', '', 0, '[]', '[]', '[]')")
    con.execute("INSERT INTO agents VALUES ('kid', 'root', 'Kid', '', '', '', 0, '[\"x\"]', '[]', '[]')")
    con.commit()
    con.close()

    db.configure(path)
    from voice_orchestrator.webapi import repository, seed

    with db.session_scope() as s:
        assert seed.seed_if_empty(s) is True  # only the project row: the agents were kept
        root = repository.build_tree(s, "demo")
        assert root.id == "root" and root.children[0].triggers == ["x"]
        assert seed.seed_if_empty(s) is False


def test_a_failing_model_costs_the_caller_an_apology_not_silence(monkeypatch):
    from voice_orchestrator.llm import LLMProvider, ResilientProvider
    from voice_orchestrator.voice.bridge import new_voice_bridge

    class Broken(LLMProvider):
        def classify(self, *a, **k):
            raise RuntimeError("401 invalid x-api-key")

        def respond(self, *a, **k):
            raise RuntimeError("401 invalid x-api-key")

        def summarize(self, *a, **k):
            raise RuntimeError("401 invalid x-api-key")

    monkeypatch.setattr(project, "cached_provider", lambda *a, **k: Broken())
    bridge = new_voice_bridge("resilient")
    result = bridge.turn("Quanto costa il roaming in Francia?")
    assert result.agent.id == "roaming"  # routing still worked (keywords)
    assert result.reply == ResilientProvider.FALLBACK_REPLY
    assert bridge.is_simulated(result.agent) is False
