"""The LiveKit Agents worker entrypoint — the only thing in this project
that actually opens a real-time audio pipeline. Run it with:

    python -m voice_orchestrator.voice.worker dev

`dev` connects to LiveKit's hosted Agents Playground for a live test from a
browser tab with your own microphone, no telephony or custom web client
needed; `start` runs it as a long-lived worker (what you'd point at real
rooms/SIP trunking later). See README's "Voice layer" section for how to
get LIVEKIT_URL/API_KEY/API_SECRET, a DEEPGRAM_API_KEY, and an
ELEVENLABS_API_KEY — the four free-tier accounts this needs before `dev`
will actually connect to anything.

Everything specific to voice-orchestrator is the three lines inside
entrypoint(): build one VoiceBridge, wrap it in one OrchestratorAgent,
start one AgentSession around it. STT/VAD/TTS provider choice lives here
and only here — swapping Deepgram for another STT, say, is a one-line
change in this file; bridge.py and agent.py don't know or care which
providers are plugged in above them.

`request_fnc` is the other piece worth noticing: it runs `usage_guard.py`'s
daily call-minutes cap *before* a call is even accepted, which is the only
hook point that avoids spending anything at all on a call that's over
budget (rejecting a job never spins up a room or touches Deepgram/
ElevenLabs). `entrypoint`'s shutdown callback is the other half — it's what
records how long the call actually ran, once it ends, and also files the
call in `call_log.jsonl` (`..call_log`) for the agent-builder's analytics
dashboard — the same record `chat` and the webapi's test-route endpoint
write, just from this surface.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from livekit.agents import Agent, AgentSession, JobContext, JobRequest, WorkerOptions, cli
from livekit.plugins import deepgram, elevenlabs, silero

from .. import call_log
from .agent import OrchestratorAgent
from .bridge import VoiceBridge, new_voice_bridge
from .usage_guard import UsageGuard

_guard = UsageGuard()


def _build_bridge(ctx: JobContext) -> VoiceBridge:
    return new_voice_bridge(call_id=ctx.job.id)


async def request_fnc(req: JobRequest) -> None:
    """LiveKit's own default request_fnc is just `await req.accept()` — this
    adds exactly one check in front of that: has today's call-minutes
    budget already been used? If so, reject outright rather than accept
    and immediately hang up — a rejected job never creates a room or opens
    an STT/TTS connection, so it's the only response that costs nothing."""
    if not _guard.can_start_call():
        await req.reject()
        return
    await req.accept()


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    started_at = time.monotonic()
    started_wall = datetime.now(timezone.utc)
    bridge = _build_bridge(ctx)

    async def _record_usage() -> None:
        _guard.record_call(time.monotonic() - started_at)
        # Same shutdown hook also files this call in call_log.jsonl for the
        # agent-builder's analytics dashboard — one real call, recorded once,
        # whether it ran its full course or the caller just hung up.
        call_log.append(call_log.from_session(bridge.session, source="voice", started_at=started_wall))

    ctx.add_shutdown_callback(_record_usage)

    session = AgentSession(
        vad=silero.VAD.load(),
        # Nova-3 with language="multi" rather than pinning "it": Deepgram's
        # multi-language mode code-switches within a single call, which
        # suits a caller who might drop into English mid-sentence better
        # than a fixed Italian model would — and it's one STT instance
        # instead of needing to pick a language up front. Pin
        # language="it" instead if you'd rather trade that flexibility for
        # a small accuracy bump on Italian-only calls.
        stt=deepgram.STT(model="nova-3", language="multi"),
        # ElevenLabs' Flash v2.5 model — picked specifically for the
        # sub-300ms voice round-trip budget the architecture research set;
        # eleven_turbo_v2_5 (this plugin's own default) trades some of that
        # latency back for quality, which isn't the right trade for a live
        # phone-style conversation.
        tts=elevenlabs.TTS(model="eleven_flash_v2_5"),
        # No llm= here: OrchestratorAgent.llm_node() never delegates to
        # Agent.default.llm_node(), so there's no real chat model for
        # AgentSession to ever actually call — see agent.py's docstring for
        # why that's deliberate rather than an oversight.
    )
    await session.start(agent=OrchestratorAgent(bridge), room=ctx.room)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, request_fnc=request_fnc))
