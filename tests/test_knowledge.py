"""Blocco 5 — knowledge base: the core (`knowledge.py`: chunking, search,
cache invalidation) and the agent builder's API over it (documents from
text/file/URL, delete, preview). Nothing here touches the network: URL
fetching runs against an injected httpx.MockTransport."""
from __future__ import annotations

import shutil

import httpx
import pytest
from fastapi.testclient import TestClient

from conftest import configure_test_db
from voice_orchestrator import config, knowledge
from voice_orchestrator.agents.registry import AgentSpec, ToolBinding
from voice_orchestrator.state import CallSession
from voice_orchestrator.tools.knowledge_tool import KnowledgeLookupTool
from voice_orchestrator.webapi import db, knowledge_repository
from voice_orchestrator.webapi.app import app

DEMO_DIR = config.KNOWLEDGE_DIR


@pytest.fixture
def kb_dir(tmp_path, monkeypatch):
    target = tmp_path / "knowledge"
    shutil.copytree(DEMO_DIR, target)
    monkeypatch.setattr(config, "KNOWLEDGE_DIR", target)
    return target


@pytest.fixture
def client(tmp_path, monkeypatch, kb_dir):
    configure_test_db(tmp_path, monkeypatch, "kb_agents.db")
    monkeypatch.setattr(config, "CALL_LOG_FILE", tmp_path / "call_log.jsonl")
    monkeypatch.setattr(config, "WEBHOOK_LOG_FILE", tmp_path / "webhook_log.jsonl")
    monkeypatch.setattr(config, "PROVIDER", "fake")
    with TestClient(app) as c:
        yield c


# ---- core ----


def test_chunking_splits_on_sections_and_drops_the_title_only_section():
    chunks = knowledge.chunk_text("# Titolo\n\n## Uno\ntesto uno\n\n## Due\ntesto due")
    assert chunks == ["## Uno\ntesto uno", "## Due\ntesto due"]


def test_chunking_splits_long_sections_on_paragraphs_keeping_the_heading():
    para = "Il modem si riavvia così. " * 30  # ~780 chars
    text = "## Modem\n" + "\n\n".join([para] * 4)
    chunks = knowledge.chunk_text(text)
    assert len(chunks) > 1
    assert all(len(c) <= knowledge.MAX_CHUNK_CHARS + len("## Modem\n") for c in chunks)
    assert all(c.startswith("## Modem") for c in chunks)


def test_text_without_headers_still_becomes_several_chunks():
    text = "\n\n".join(f"Paragrafo {i}. " + "parola " * 150 for i in range(6))
    assert len(knowledge.chunk_text(text)) >= 3


def test_search_ranks_and_drops_zero_scores(kb_dir):
    hits = knowledge.search(["internet_troubleshooting.md"], "wifi interference 5GHz band", top_k=5)
    assert hits and "Wifi vs wired" in hits[0].text
    assert all(h.score > 0 for h in hits)
    assert knowledge.search(["internet_troubleshooting.md"], "zzzz qqqq", top_k=5) == []


def test_search_sees_a_file_edited_after_the_first_query(kb_dir):
    (kb_dir / "nuovo.md").write_text("## Uno\nla parola segreta è mandarino\n", encoding="utf-8")
    assert knowledge.search(["nuovo.md"], "ananas", top_k=1) == []
    (kb_dir / "nuovo.md").write_text("## Uno\nla parola segreta è ananas, non mandarino\n", encoding="utf-8")
    assert knowledge.search(["nuovo.md"], "ananas", top_k=1)


def test_tool_reports_sources_and_says_nothing_to_the_caller_when_nothing_matches(kb_dir):
    agent = AgentSpec(
        id="t", name="T", description="d", tools=[ToolBinding(id="knowledge_lookup")], knowledge=["internet_troubleshooting.md"]
    )
    tool = KnowledgeLookupTool()
    hit = tool.run(agent, "the wifi band", CallSession(call_id="k1"))
    assert hit.data["sources"][0]["document"] == "internet_troubleshooting.md"
    miss = tool.run(agent, "voglio un operatore", CallSession(call_id="k2"))
    assert miss.data["passages"] == [] and miss.caller_text == ""


# ---- API ----


def test_list_includes_demo_files_with_chunks_and_users(client):
    docs = {d["name"]: d for d in client.get("/api/knowledge").json()["documents"]}
    internet = docs["internet_troubleshooting.md"]
    assert internet["exists"] and internet["chunk_count"] == 5
    assert internet["used_by"] == ["tech_internet"]


def test_add_text_document_then_read_it_back(client):
    r = client.post("/api/knowledge", json={"name": "Orari negozi", "content": "## Milano\nAperto 9-19.\n"})
    assert r.status_code == 201
    assert r.json()["name"] == "Orari_negozi.md" and r.json()["source_type"] == "text"
    doc = client.get("/api/knowledge/Orari_negozi.md").json()
    assert doc["chunks"] == [{"index": 0, "text": "## Milano\nAperto 9-19."}]

    dup = client.post("/api/knowledge", json={"name": "Orari negozi", "content": "x"})
    assert dup.status_code == 409
    over = client.post("/api/knowledge", json={"name": "Orari negozi", "content": "## Roma\nchiuso", "overwrite": True})
    assert over.status_code == 201


def test_add_sanitizes_names_and_rejects_empty_content(client, kb_dir):
    r = client.post("/api/knowledge", json={"name": "../evil", "content": "## a\nb"})
    assert r.status_code == 201 and r.json()["name"] == "evil.md"  # path parts stripped, not followed
    assert client.get("/api/knowledge/evil.md").status_code == 200
    assert client.post("/api/knowledge", json={"name": "/// ..", "content": "x"}).status_code == 400
    assert client.post("/api/knowledge", json={"name": "vuoto", "content": "   "}).status_code == 400
    assert client.post("/api/knowledge", json={"name": "titoli", "content": "# Solo\n## Titoli"}).status_code == 400


def test_delete_refuses_a_document_in_use_and_removes_an_unused_one(client, kb_dir):
    r = client.delete("/api/knowledge/internet_troubleshooting.md")
    assert r.status_code == 409 and "tech_internet" in r.json()["detail"]

    client.post("/api/knowledge", json={"name": "temp", "content": "## A\nb"})
    assert client.delete("/api/knowledge/temp.md").status_code == 204
    assert not (kb_dir / "temp.md").exists()
    assert client.get("/api/knowledge/temp.md").status_code == 404


def test_missing_file_referenced_by_an_agent_is_listed(client):
    client.put("/api/agents/tech_tv", json={**client.get("/api/agents/tech_tv").json(), "knowledge": ["sparito.md"]})
    docs = {d["name"]: d for d in client.get("/api/knowledge").json()["documents"]}
    assert docs["sparito.md"]["exists"] is False and docs["sparito.md"]["used_by"] == ["tech_tv"]


def test_preview_by_agent_matches_what_the_tool_retrieves(client):
    body = client.post("/api/knowledge/search", json={"query": "router lights red", "agent_id": "tech_internet"}).json()
    assert body["documents"] == ["internet_troubleshooting.md"]
    assert body["hits"] and body["hits"][0]["score"] >= body["hits"][-1]["score"]
    expected = knowledge.search(("internet_troubleshooting.md",), "router lights red", top_k=3)
    assert [h["text"] for h in body["hits"]] == [h.text for h in expected]
    assert client.post("/api/knowledge/search", json={"query": "x", "agent_id": "nope"}).status_code == 404


def test_add_from_url_extracts_page_sections(client, monkeypatch):
    html = """<html><head><title>Guida Fibra</title><script>var x=1;</script></head><body>
      <nav>Menu Home Contatti</nav>
      <h2>Installazione</h2><p>Collega la fibra alla presa ottica.</p>
      <h2>Problemi</h2><ul><li>Luce rossa: guasto di linea</li><li>Luce verde: ok</li></ul>
    </body></html>"""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "example.com"
        return httpx.Response(200, text=html, headers={"content-type": "text/html; charset=utf-8"})

    monkeypatch.setattr(knowledge_repository, "_url_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(knowledge_repository, "_is_private_host", lambda host: False)
    r = client.post("/api/knowledge/from-url", json={"url": "https://example.com/fibra"})
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "guida_fibra.md" and r.json()["source_url"] == "https://example.com/fibra"

    doc = client.get("/api/knowledge/guida_fibra.md").json()
    assert "var x" not in doc["content"] and "Menu Home" not in doc["content"]
    texts = [c["text"] for c in doc["chunks"]]
    assert any(t.startswith("## Problemi") and "- Luce rossa: guasto di linea" in t for t in texts)


def test_add_from_url_refuses_private_hosts_and_non_text(client, monkeypatch):
    r = client.post("/api/knowledge/from-url", json={"url": "http://127.0.0.1:8000/api/health"})
    assert r.status_code == 502 and "private" in r.json()["detail"]
    assert client.post("/api/knowledge/from-url", json={"url": "file:///etc/passwd"}).status_code == 502

    monkeypatch.setattr(
        knowledge_repository,
        "_url_transport",
        httpx.MockTransport(lambda req: httpx.Response(200, content=b"%PDF-1.7", headers={"content-type": "application/pdf"})),
    )
    monkeypatch.setattr(knowledge_repository, "_is_private_host", lambda host: False)
    r = client.post("/api/knowledge/from-url", json={"url": "https://example.com/doc.pdf"})
    assert r.status_code == 502 and "Unsupported" in r.json()["detail"]
