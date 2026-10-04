"""LiveKit Agents integration — the only file in this project that imports
`livekit-agents`. All it does is: pull the latest caller utterance out of
the chat context LiveKit's session hands `llm_node()`, run it through the
*existing* text-core orchestrator via a `VoiceBridge`, and yield the reply
text back as the "LLM" output.

STT (Deepgram) and VAD (Silero) are configured once, in worker.py, and
never touched here. `llm_node` is this project's central extension point:
the router/tools/memory stack `orchestrator.py` already has IS the "LLM"
step for this agent — we're deliberately not calling a real chat model at
all (no `Agent.default.llm_node(...)` delegation, unlike the override
pattern LiveKit's own docs show for pre/post-processing a model's output),
because the whole thesis of this project is that a deterministic router +
scoped tools beats a general chat model deciding, turn by turn, what to
do. Letting a real LLM sit in this seat too would just mean two different
things arguing over who's driving the call.

TTS (ElevenLabs) is also configured once in worker.py as the *family-wide*
default, but blocco 2 lets an individual agent override voice_id/
stability/speed — `tts_node()` below is the second extension point that
makes that real, by swapping `self._tts` in for the duration of one
synthesis when the agent that produced the current reply has an override,
and falling back to worker.py's default otherwise.
"""
from __future__ import annotations

from typing import AsyncIterable

import asyncio

from livekit import rtc
from livekit.agents import Agent, FunctionTool, ModelSettings, get_job_context, llm
from livekit.plugins import elevenlabs

from ..agents.registry import AgentSpec
from .bridge import VoiceBridge, is_actionable

_DEFAULT_INSTRUCTIONS = (
    "Voice orchestrator — this agent's replies are produced entirely by "
    "voice_orchestrator's own router/tools/memory stack (see bridge.py and "
    "orchestrator.py), not by an LLM reading these instructions. This text "
    "exists only because LiveKit's Agent base class requires some "
    "`instructions` string at construction time."
)


def _latest_user_text(chat_ctx: "llm.ChatContext") -> str:
    """`chat_ctx.messages` is the whole visible history LiveKit's session
    has built up for this turn (system prompt, prior turns, the newest
    caller utterance last) — only the last one is new. Everything before it
    is already sitting in CallSession's own turn history via
    `handle_turn()`'s `session.add_turn()` calls, so handing the whole
    history to the router again would double-count every prior turn."""
    for message in reversed(chat_ctx.messages()):
        if message.role == "user":
            return message.text_content or ""
    return ""


class OrchestratorAgent(Agent):
    """One instance per LiveKit job (= one phone call). `bridge` already
    carries its own `CallSession`, so this class itself stays stateless —
    all per-call state lives in the bridge, the same separation
    orchestrator.py keeps between its (stateless) routing/tool functions
    and the (stateful) CallSession object they're handed."""

    def __init__(self, bridge: VoiceBridge, instructions: str = "") -> None:
        super().__init__(instructions=instructions or _DEFAULT_INSTRUCTIONS)
        self._bridge = bridge
        # Per-agent ElevenLabs TTS instances (blocco 2, fixes D1), cached by
        # (voice_id, stability, speed) — elevenlabs.TTS() doesn't open a
        # network connection at construction time, so this just avoids
        # rebuilding the Python object on every single turn.
        self._tts_cache: dict[tuple[str, float | None, float | None], elevenlabs.TTS] = {}
        self._hangup_scheduled = False

    def _tts_for_agent(self, agent: AgentSpec) -> elevenlabs.TTS | None:
        """None when the agent has no voice_id override — tts_node() below
        then falls back to whatever TTS AgentSession was built with in
        worker.py, same as before blocco 2."""
        if not agent.voice_id:
            return None
        key = (agent.voice_id, agent.voice_stability, agent.voice_speed)
        cached = self._tts_cache.get(key)
        if cached is not None:
            return cached
        extra: dict = {}
        if agent.voice_stability is not None or agent.voice_speed is not None:
            settings_kwargs: dict = {
                "stability": agent.voice_stability if agent.voice_stability is not None else 0.5,
                "similarity_boost": 0.75,
            }
            if agent.voice_speed is not None:
                settings_kwargs["speed"] = agent.voice_speed
            extra["voice_settings"] = elevenlabs.VoiceSettings(**settings_kwargs)
        tts = elevenlabs.TTS(voice_id=agent.voice_id, **extra)
        self._tts_cache[key] = tts
        return tts

    async def llm_node(
        self,
        chat_ctx: llm.ChatContext,
        tools: list[FunctionTool],
        model_settings: ModelSettings,
    ) -> AsyncIterable[str]:
        utterance = _latest_user_text(chat_ctx)
        if not is_actionable(utterance):
            return
        # handle_turn() is synchronous and may itself call asyncio.run()
        # (MCPTool.run() does, to talk to an MCP server over stdio) — calling
        # it directly here would crash with "asyncio.run() cannot be called
        # from a running event loop", because llm_node is already running
        # inside LiveKit's own loop. to_thread() runs it on a worker thread,
        # which is free to start its own new event loop.
        result = await asyncio.to_thread(self._bridge.turn, utterance)
        if result.reply:
            yield result.reply
        # Built-in `end_call` tool (blocco 2): handle_turn() just sets this
        # slot, same mechanism as transfer_to_human's `transferred` flag —
        # the actual hangup is a voice-layer concern, so it lives here.
        if self._bridge.session.slots.get("call_ended") and not self._hangup_scheduled:
            self._hangup_scheduled = True
            asyncio.create_task(self._hang_up_after_speaking(result.reply))

    async def _hang_up_after_speaking(self, reply: str) -> None:
        """Best-effort: waits roughly as long as the farewell takes to say
        before ending the room, rather than cutting the caller off
        mid-goodbye. This is a word-count heuristic, not a real wait on
        audio playback finishing — llm_node only yields text, and the TTS
        timing happens further down LiveKit's own pipeline, outside what
        this method observes. See docs/ROADMAP.md debt D12: this hasn't
        been run against a live call in this environment (no LiveKit/
        ElevenLabs credentials here), only reasoned through against the
        installed livekit-agents API."""
        word_count = len(reply.split())
        await asyncio.sleep(max(1.5, word_count * 0.35))
        ctx = get_job_context(required=False)
        if ctx is not None:
            await ctx.delete_room()

    async def tts_node(
        self, text: AsyncIterable[str], model_settings: ModelSettings
    ) -> AsyncIterable[rtc.AudioFrame]:
        """Per-agent ElevenLabs voice (blocco 2, fixes D1's "voice field
        saved but never connected to the TTS"). `Agent.tts` is a plain
        instance attribute (what `tts=` at `Agent.__init__` sets) that the
        default `tts_node` reads at call time — its own docstring says a
        value set here is picked up "at runtime" by the session, which is
        the documented mechanism this relies on, not an internal/private
        one. Swapped back in `finally` so a later turn by an agent with no
        voice override goes back to worker.py's own default TTS.

        Same caveat as `_hang_up_after_speaking`: reasoned through against
        livekit-agents 1.8.4's actual API, not exercised against a live
        call in this environment."""
        current_id = self._bridge.session.current_agent_id
        agent_spec = self._bridge.root.find(current_id) if current_id else None
        per_agent_tts = self._tts_for_agent(agent_spec) if agent_spec else None
        if per_agent_tts is None:
            async for frame in Agent.default.tts_node(self, text, model_settings):
                yield frame
            return
        previous_tts = self._tts
        self._tts = per_agent_tts
        try:
            async for frame in Agent.default.tts_node(self, text, model_settings):
                yield frame
        finally:
            self._tts = previous_tts
