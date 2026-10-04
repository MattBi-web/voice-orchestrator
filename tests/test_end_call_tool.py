"""The built-in `end_call` tool (blocco 2) — same shape test as
transfer_to_human would get: should_trigger() on the Italian closing
phrases it's meant to catch, run() setting the session flag the voice
layer (voice/agent.py) acts on to actually hang up.
"""
from __future__ import annotations

from voice_orchestrator.agents.registry import AgentSpec
from voice_orchestrator.state import CallSession
from voice_orchestrator.tools import REGISTRY, get_tool
from voice_orchestrator.tools.end_call_tool import EndCallTool


def _agent() -> AgentSpec:
    return AgentSpec(id="router", name="Router", description="d")


def test_registered_under_its_id():
    assert "end_call" in REGISTRY
    assert isinstance(get_tool("end_call"), EndCallTool)


def test_triggers_on_a_closing_phrase():
    tool = EndCallTool()
    session = CallSession(call_id="t1")
    assert tool.should_trigger(_agent(), "no grazie, basta così", session) is True


def test_does_not_trigger_on_an_unrelated_utterance():
    tool = EndCallTool()
    session = CallSession(call_id="t2")
    assert tool.should_trigger(_agent(), "quanto costa il roaming in Francia?", session) is False


def test_run_sets_the_call_ended_slot():
    tool = EndCallTool()
    session = CallSession(call_id="t3")

    result = tool.run(_agent(), "arrivederci", session)

    assert session.slots["call_ended"] is True
    assert result.data == {"call_ended": True}
    assert result.summary  # an LLM instruction, not caller-facing text (same pattern as transfer_tool)
