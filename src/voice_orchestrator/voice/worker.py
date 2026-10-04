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
"""
from __future__ import annotations

from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli
from livekit.plugins import deepgram, elevenlabs, silero

from .agent import OrchestratorAgent
from .bridge import new_voice_bridge


def _build_agent(ctx: JobContext) -> Agent:
    return OrchestratorAgent(new_voice_bridge(call_id=ctx.job.id))


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()

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
    await session.start(agent=_build_agent(ctx), room=ctx.room)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
