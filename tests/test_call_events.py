"""Blocco 7, fase C — the events the live call page is built from. Core
only: no livekit needed."""
from __future__ import annotations

from voice_orchestrator import call_events
from voice_orchestrator.agents.registry import load_family
from voice_orchestrator.config import AGENTS_FILE
from voice_orchestrator.llm import FakeProvider
from voice_orchestrator.orchestrator import handle_turn
from voice_orchestrator.state import CallSession


def _turn(utterance: str, session: CallSession | None = None):
    root = load_family(AGENTS_FILE)
    session = session or CallSession(call_id="ev", channel="voice")
    from_id = session.current_agent_id or root.id
    result = handle_turn(session, root, utterance, FakeProvider())
    return call_events.turn_event(root, from_id, utterance, result, session, seq=1)


def test_pattern_turn_names_the_keyword_and_the_handover():
    ev = _turn("Quanto costa il roaming in Francia?")
    assert ev["type"] == "turn" and ev["resolved_by"] == "pattern"
    assert ev["agent_id"] == "roaming" and ev["from_agent_id"] == "router" and ev["handed_off"] is True
    assert ev["keyword"] == "roaming"
    assert ev["tools"] == ["mcp:demo"]
    assert ev["latency_ms"] is not None
    assert ev["simulated"] is False  # set by the caller, which knows the provider


def test_gate_exclusion_is_explained_with_its_rule():
    ev = _turn("Ho un problema con la bolletta")
    assert {"id": "billing", "name": "Billing Agent", "rule": "authenticated == true"} in ev["excluded"]
    assert "billing" not in ev["eligible"]
    assert ev["resolved_by"] == "llm_fallback" and ev["handed_off"] is False and ev["keyword"] is None


def test_greeting_and_end_events():
    root = load_family(AGENTS_FILE)
    assert call_events.greeting_event(root, "Pronto")["agent_id"] == "router"
    assert call_events.ended_event("end_call") == {"type": "ended", "reason": "end_call"}
