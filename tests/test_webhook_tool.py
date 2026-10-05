"""Tests webhook_tool.py's real request-building/response-parsing code path
against a fully offline httpx.MockTransport — no real socket, no external
dependency, but the exact same `WebhookTool.run()` code a live call goes
through (only the transport is swapped), same spirit as test_mcp_tool.py
spawning the real demo MCP server rather than mocking MCPTool itself.
"""
from __future__ import annotations

import httpx
import pytest

from voice_orchestrator import config
from voice_orchestrator.agents.registry import load_family
from voice_orchestrator.llm import FakeProvider
from voice_orchestrator.orchestrator import handle_turn
from voice_orchestrator.state import CallSession
from voice_orchestrator.tools import webhook_log
from voice_orchestrator.tools.webhook_tool import (
    SecretNotConfigured,
    WebhookParam,
    WebhookTool,
    WebhookToolConfig,
    read_configs,
    resolve_header_value,
)


@pytest.fixture(autouse=True)
def _isolated_webhook_log(tmp_path, monkeypatch):
    # Every test gets its own throwaway log, for the same reason
    # test_webapi.py's `client` fixture isolates CALL_LOG_FILE: nothing here
    # should touch a developer's real data/webhook_log.jsonl.
    monkeypatch.setattr(config, "WEBHOOK_LOG_FILE", tmp_path / "test_webhook_log.jsonl")


def _config(**overrides) -> WebhookToolConfig:
    base = dict(
        name="order_status",
        description="Looks up an order's shipping status.",
        url="https://example.test/orders",
        method="POST",
        headers={"Content-Type": "application/json"},
        params=[WebhookParam(name="order_id", source="slot", value="order_id")],
        triggers=("dov'è il mio ordine", "stato spedizione"),
    )
    base.update(overrides)
    return WebhookToolConfig(**base)


def test_webhook_tool_id_and_trigger():
    tool = WebhookTool(_config())
    assert tool.id == "webhook:order_status"
    session = CallSession(call_id="t")
    assert tool.should_trigger(agent=None, utterance="Dov'è il mio ordine?", session=session) is True
    assert tool.should_trigger(agent=None, utterance="buongiorno", session=session) is False


def test_webhook_tool_fires_a_real_request_against_a_mock_transport():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        return httpx.Response(200, json={"status": "shipped", "eta": "2026-10-10"})

    tool = WebhookTool(_config(), transport=httpx.MockTransport(handler))
    session = CallSession(call_id="t-1", slots={"order_id": "ORD-42"})

    result = tool.run(agent=type("A", (), {"id": "sales"})(), utterance="dov'è il mio ordine?", session=session)

    assert seen["method"] == "POST"
    assert seen["url"] == "https://example.test/orders"
    assert "shipped" in result.summary
    assert result.data["status_code"] == 200

    # The execution the call above just logged (to the isolated throwaway
    # file the autouse fixture pointed WEBHOOK_LOG_FILE at) round-trips
    # through read_all() with the right shape.
    execs = webhook_log.read_all()
    assert execs, "expected at least one execution to have been logged"
    last = execs[-1]
    assert last.tool_name == "order_status"
    assert last.ok is True
    assert last.status_code == 200
    assert last.call_id == "t-1"


def test_webhook_tool_get_sends_params_as_query_string():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.params["order_id"] == "ORD-7"
        return httpx.Response(200, text="ok")

    tool = WebhookTool(_config(method="GET"), transport=httpx.MockTransport(handler))
    session = CallSession(call_id="t-2", slots={"order_id": "ORD-7"})
    result = tool.run(agent=type("A", (), {"id": "sales"})(), utterance="stato spedizione", session=session)
    assert result.data["status_code"] == 200


def test_webhook_tool_http_error_status_is_reported_not_raised():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    tool = WebhookTool(_config(), transport=httpx.MockTransport(handler))
    session = CallSession(call_id="t-3", slots={"order_id": "ORD-1"})
    result = tool.run(agent=type("A", (), {"id": "sales"})(), utterance="stato spedizione", session=session)
    assert "500" in result.summary
    assert result.data["status_code"] == 500

    last = webhook_log.read_all()[-1]
    assert last.ok is False
    assert last.status_code == 500


def test_webhook_tool_connection_failure_does_not_raise():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    tool = WebhookTool(_config(), transport=httpx.MockTransport(handler))
    session = CallSession(call_id="t-4", slots={"order_id": "ORD-1"})
    result = tool.run(agent=type("A", (), {"id": "sales"})(), utterance="stato spedizione", session=session)
    assert "failed to reach" in result.summary

    last = webhook_log.read_all()[-1]
    assert last.ok is False
    assert last.status_code is None
    assert last.error


def test_resolve_header_value_literal_passes_through():
    assert resolve_header_value("application/json") == "application/json"


def test_resolve_header_value_resolves_secret_from_env(monkeypatch):
    monkeypatch.setenv("VOICE_ORCH_SECRET_MY_KEY", "sk-live-123")
    assert resolve_header_value("{{secret:MY_KEY}}") == "sk-live-123"


def test_resolve_header_value_raises_when_secret_missing(monkeypatch):
    monkeypatch.delenv("VOICE_ORCH_SECRET_MISSING", raising=False)
    try:
        resolve_header_value("{{secret:MISSING}}")
        assert False, "expected SecretNotConfigured"
    except SecretNotConfigured as exc:
        assert "VOICE_ORCH_SECRET_MISSING" in str(exc)


def test_webhook_tool_misconfigured_secret_fails_the_call_without_crashing(monkeypatch):
    monkeypatch.delenv("VOICE_ORCH_SECRET_MISSING", raising=False)
    cfg = _config(headers={"X-Api-Key": "{{secret:MISSING}}"})
    tool = WebhookTool(cfg)  # no transport needed — fails before any request is made
    session = CallSession(call_id="t-5", slots={"order_id": "ORD-1"})
    result = tool.run(agent=type("A", (), {"id": "sales"})(), utterance="stato spedizione", session=session)
    assert "misconfigured" in result.summary
    assert "VOICE_ORCH_SECRET_MISSING" in result.summary

    last = webhook_log.read_all()[-1]
    assert last.ok is False
    assert "VOICE_ORCH_SECRET_MISSING" in last.error


def test_read_configs_reads_the_bundled_demo_yaml():
    configs = read_configs(config.WEBHOOK_TOOLS_FILE)
    assert any(c.name == "network_status" for c in configs)
    demo = next(c for c in configs if c.name == "network_status")
    assert demo.url == "https://httpbin.org/anything"
    assert demo.method == "POST"
    assert demo.params[0].value == "account_number"


def test_tech_internet_agent_wired_to_the_demo_webhook_tool():
    root = load_family(config.AGENTS_FILE)
    tech_internet = root.find("tech_internet")
    assert tech_internet is not None
    assert any(t.id == "webhook:network_status" for t in tech_internet.tools)


def test_webhook_tool_not_triggered_leaves_the_rest_of_the_turn_unaffected():
    """Full orchestrator pass through an unrelated utterance — the demo
    webhook tool must not fire (and therefore not require network) just
    because the agent that owns it is reached. Two turns to get there:
    router -> tech_support -> tech_internet, same path test_routing.py's
    own wifi test takes."""
    root = load_family(config.AGENTS_FILE)
    session = CallSession(call_id="test-webhook-no-trigger")
    provider = FakeProvider()
    handle_turn(session, root, "il wifi non si connette", provider)
    result = handle_turn(session, root, "il router ha la luce rossa", provider)
    assert result.agent.id == "tech_internet"
    assert "webhook:network_status" not in result.tool_ids_used
