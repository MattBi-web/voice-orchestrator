"""D12 — the voice layer driven through livekit-agents' real AgentSession
pipeline (voice/harness.py: text turns in, audio captured in memory, no
room, no network). Skipped when the `voice` extra isn't installed.

What it pins down:
- the agent actually replies to a user turn (livekit-agents skips the
  reply when no LLM is configured — RouterLLM exists for that);
- after a handoff the reply is synthesized with the new agent's voice, and
  an agent without an override uses the session's default TTS;
- end_call hangs up only once the farewell has finished playing.
"""
from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("livekit.agents")
pytest.importorskip("livekit.plugins.elevenlabs")

from voice_orchestrator.agents.registry import AgentSpec, ToolBinding  # noqa: E402
from voice_orchestrator.voice.agent import RouterLLM  # noqa: E402
from voice_orchestrator.voice.harness import FakeTTS, run_scripted_call  # noqa: E402


def _family() -> AgentSpec:
    billing = AgentSpec(
        id="billing", name="Billing", description="bollette pagamenti", triggers=["bolletta"],
        voice_id="voce_billing", tools=[ToolBinding(id="end_call")],
    )
    sales = AgentSpec(id="sales", name="Sales", description="offerte", triggers=["offerta"], voice_id="voce_sales")
    return AgentSpec(id="router", name="Router", description="smista", children=[billing, sales])


def _run(utterances):
    return asyncio.run(
        run_scripted_call(_family(), utterances, FakeTTS(), lambda spec: FakeTTS(spec.voice_id), playout_speed=4.0)
    )


def test_agent_carries_a_placeholder_llm_that_is_never_called():
    with pytest.raises(RuntimeError, match="never called"):
        RouterLLM().chat(chat_ctx=None)


def test_voice_follows_the_agent_that_answers_and_hangup_waits_for_playout():
    call = _run(["ciao", "ho un problema con la bolletta", "arrivederci"])

    assert [a for a, _ in call.replies] == ["router", "billing", "billing"]
    assert [s.voice for s in call.syntheses] == ["default", "voce_billing", "voce_billing"]
    assert len(call.output.segments) == 3 and not any(s.interrupted for s in call.output.segments)

    last = call.output.segments[-1]
    assert call.agent.ended_at is not None
    assert call.agent.ended_at >= last.finished_at  # not before the goodbye finished playing


def test_no_hangup_without_end_call():
    call = _run(["ciao", "vorrei una nuova offerta"])
    assert [s.voice for s in call.syntheses] == ["default", "voce_sales"]
    assert call.agent.ended_at is None
