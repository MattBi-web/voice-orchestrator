"""Tests for the voice layer's one LiveKit-free module: bridge.py. These
run with zero extra dependencies — no livekit-agents, no STT/TTS/VAD
plugins — exercising exactly the logic agent.py's llm_node() delegates to
(is_actionable() + VoiceBridge.turn()), so the STT-transcript-to-reply path
is covered without needing a real LiveKit connection, a microphone, or any
API key, same zero-API-key testability as the rest of this project.
"""
from __future__ import annotations

from voice_orchestrator.agents.registry import load_family
from voice_orchestrator.llm import FakeProvider
from voice_orchestrator.state import CallSession
from voice_orchestrator.voice.bridge import VoiceBridge, is_actionable, new_voice_bridge
from voice_orchestrator import config


def test_is_actionable():
    assert is_actionable("ciao, come posso avere il conto?") is True
    assert is_actionable("") is False
    assert is_actionable("   ") is False
    assert is_actionable(None) is False


def test_bridge_turn_runs_a_real_handle_turn_and_returns_a_reply():
    root = load_family(config.AGENTS_FILE)
    bridge = VoiceBridge(session=CallSession(call_id="voice-test-1"), root=root, provider=FakeProvider())

    result = bridge.turn("buongiorno, posso parlare con il supporto?")

    assert result.reply
    assert result.agent is not None
    # The same CallSession the bridge was built with records the turn —
    # this is what lets a second .turn() call see the first one's context,
    # exactly like a real multi-turn phone call.
    assert len(bridge.session.turns) == 2  # caller + agent


def test_bridge_turn_is_stateful_across_multiple_calls():
    """A real call is many llm_node() invocations against the *same*
    bridge/session — not a fresh one per utterance. Two turns through one
    bridge should accumulate history the way CallSession.add_turn() always
    has, not reset it."""
    root = load_family(config.AGENTS_FILE)
    bridge = VoiceBridge(session=CallSession(call_id="voice-test-2"), root=root, provider=FakeProvider())

    bridge.turn("buongiorno")
    bridge.turn("quanto costa il roaming in Francia?")

    assert len(bridge.session.turns) == 4
    assert len(bridge.session.routing_log) == 2


def test_new_voice_bridge_wires_channel_voice():
    bridge = new_voice_bridge(call_id="voice-test-3", provider=FakeProvider())
    assert bridge.session.channel == "voice"
    assert bridge.session.call_id == "voice-test-3"
