"""D10: a tool's `summary` is written for an LLM and can be an instruction
("Tell the caller, briefly…"). FakeProvider can't follow instructions, so
it must read the caller-facing `caller_note` instead — otherwise the
instruction itself ends up as the reply in transcripts and in the try-it box.
"""
from __future__ import annotations

from voice_orchestrator.agents.registry import AgentSpec, ToolBinding
from voice_orchestrator.llm import FakeProvider
from voice_orchestrator.orchestrator import handle_turn
from voice_orchestrator.state import CallSession
from voice_orchestrator.tools.base import ToolResult


def _leaf(tool_id: str) -> AgentSpec:
    return AgentSpec(id="solo", name="Solo", description="d", tools=[ToolBinding(id=tool_id)])


def test_caller_note_falls_back_to_summary():
    assert ToolResult(summary="saldo 10€").caller_note == "saldo 10€"
    assert ToolResult(summary="Tell the caller X", caller_text="X").caller_note == "X"


def test_transfer_reply_is_not_the_llm_instruction():
    result = handle_turn(CallSession(call_id="d10a"), _leaf("transfer_to_human"), "voglio un operatore", FakeProvider())
    assert result.tool_ids_used == ["transfer_to_human"]
    assert "Tell the caller" not in result.reply
    assert "collega" in result.reply


def test_end_call_reply_is_a_goodbye():
    result = handle_turn(CallSession(call_id="d10b"), _leaf("end_call"), "arrivederci", FakeProvider())
    assert result.tool_ids_used == ["end_call"]
    assert "goodbye" not in result.reply.lower()
    assert "buona giornata" in result.reply


def test_real_providers_still_receive_the_llm_facing_summary():
    seen: dict = {}

    class Spy(FakeProvider):
        def respond(self, *args, **kwargs):
            seen.update(kwargs)
            return super().respond(*args, **kwargs)

    handle_turn(CallSession(call_id="d10c"), _leaf("transfer_to_human"), "voglio un operatore", Spy())
    assert any("Tell the caller" in n for n in seen["tool_notes"])
    assert not any("Tell the caller" in n for n in seen["caller_notes"])
