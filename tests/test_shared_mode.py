"""Blocco 6 — shared mode (`VOICE_ORCH_DATABASE_URL` set): the web service
and the voice worker are different machines, so everything they share
lives in the database. Runs on every test run against a SQLite *URL* (the
same code path as Postgres, minus the driver); set
VOICE_ORCH_TEST_DATABASE_URL to run it against a real Postgres too.
"""
from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_DATABASE_URL, configure_test_db
from voice_orchestrator import call_log, config, knowledge
from voice_orchestrator.state import CallSession
from voice_orchestrator.tools import webhook_log
from voice_orchestrator.voice.usage_guard import UsageGuard
from voice_orchestrator.webapi import db
from voice_orchestrator.webapi.app import app
from voice_orchestrator.webapi.models import KnowledgeDocRow

DEMO_KB = config.KNOWLEDGE_DIR


@pytest.fixture
def shared(tmp_path, monkeypatch):
    """Shared mode on, with every *file* location pointed at an empty tmp
    dir — so any accidental file write or read shows up as a failure."""
    url = TEST_DATABASE_URL or f"sqlite:///{tmp_path / 'shared.db'}"
    files = tmp_path / "files"
    monkeypatch.setattr(config, "CALL_LOG_FILE", files / "call_log.jsonl")
    monkeypatch.setattr(config, "WEBHOOK_LOG_FILE", files / "webhook_log.jsonl")
    monkeypatch.setattr(config, "USAGE_FILE", files / "usage.json")
    monkeypatch.setattr(config, "PROVIDER", "fake")
    kb = tmp_path / "seed_kb"
    shutil.copytree(DEMO_KB, kb)
    monkeypatch.setattr(config, "KNOWLEDGE_DIR", kb)
    configure_test_db(tmp_path, monkeypatch, url=url)
    yield files


def _no_files_written(files):
    return not files.exists() or not any(files.iterdir())


def test_url_normalization():
    assert db.normalize_url("postgres://u:p@h:5432/d") == "postgresql+psycopg://u:p@h:5432/d"
    assert db.normalize_url("postgresql://h/d") == "postgresql+psycopg://h/d"
    assert db.normalize_url("sqlite:///x.db") == "sqlite:///x.db"


def test_call_log_lives_in_the_database(shared):
    session = CallSession(call_id="c1")
    session.add_turn("caller", "ciao")
    from datetime import datetime, timezone

    call_log.append(call_log.from_session(session, source="voice", started_at=datetime.now(timezone.utc)))
    assert [r.call_id for r in call_log.read_all()] == ["c1"]
    assert call_log.find("c1").turns[0]["text"] == "ciao"
    assert call_log.find("nope") is None
    assert _no_files_written(shared)


def test_webhook_log_lives_in_the_database(shared):
    webhook_log.append(webhook_log.Execution("t", "c", "a", "https://x", "GET", True, 200, 12.0))
    assert [e.tool_name for e in webhook_log.read_all()] == ["t"]
    assert _no_files_written(shared)


def test_usage_cap_is_shared_across_guard_instances(shared):
    """Two worker processes = two UsageGuard objects: the tally must be one."""
    a, b = UsageGuard(max_minutes_per_day=2), UsageGuard(max_minutes_per_day=2)
    a.record_call(60)
    b.record_call(90)
    assert a.minutes_used_today() == pytest.approx(2.5)
    assert not b.can_start_call()
    assert _no_files_written(shared)


def test_knowledge_seeded_into_the_database_and_searchable(shared):
    with TestClient(app) as client:  # startup seeds agents, tools, and knowledge
        docs = {d["name"]: d for d in client.get("/api/knowledge").json()["documents"]}
        assert docs["internet_troubleshooting.md"]["exists"]

        r = client.post("/api/knowledge", json={"name": "solo_db", "content": "## A\nla parola è mandarino"})
        assert r.status_code == 201 and r.json()["chunk_count"] == 1
        assert not (config.KNOWLEDGE_DIR / "solo_db.md").exists()  # not a file in shared mode

        hits = client.post("/api/knowledge/search", json={"query": "mandarino", "documents": ["solo_db.md"]}).json()
        assert hits["hits"] and "mandarino" in hits["hits"][0]["text"]

        # An edit must reach the search index (as the worker would see it).
        client.post("/api/knowledge", json={"name": "solo_db", "content": "## A\nora è ananas", "overwrite": True})
        assert knowledge.search(["solo_db.md"], "ananas", top_k=1)
        assert not knowledge.search(["solo_db.md"], "mandarino", top_k=1)

        assert client.delete("/api/knowledge/solo_db.md").status_code == 204
        with db.session_scope() as s:
            assert s.get(KnowledgeDocRow, "solo_db.md") is None


def test_try_it_call_is_recorded_in_the_database(shared):
    with TestClient(app) as client:
        client.post("/api/test/route", json={"utterance": "il wifi non si connette"})
        calls = client.get("/api/calls").json()["calls"]
        assert len(calls) == 1 and calls[0]["source"] == "route_test"
    assert _no_files_written(shared)
