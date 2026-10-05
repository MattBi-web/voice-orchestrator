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
stability/speed. `apply_voice()` makes that real through LiveKit's public
`Agent.update_options(tts=...)` ("useful for switching a component
mid-call, e.g. a different TTS voice", per its docstring), called whenever
the agent answering changes — D12. It replaced a per-synthesis swap of the
private `self._tts` inside `tts_node()`, which worked by the same mechanism
underneath but skipped the prewarm and error/metrics wiring
`update_options` does, and could restore the wrong voice when an
interrupted reply's synthesis overlapped the next one.

Verified end to end against real ElevenLabs and the real livekit-agents
pipeline by `scripts/d12_live_check.py` (no WebRTC room needed).
"""
from __future__ import annotations

from typing import AsyncIterable, Callable

import asyncio

from livekit.agents import Agent, FunctionTool, ModelSettings, get_job_context, llm, tts
from livekit.plugins import elevenlabs

import json
import logging

from .. import call_events, config
from ..agents.registry import AgentSpec
from ..llm import FakeProvider
from .bridge import VoiceBridge, is_actionable

# Same model everywhere: the session default in worker.py and every
# per-agent voice. Flash v2.5 for the sub-300ms round-trip budget (see
# worker.py).
ELEVENLABS_MODEL = "eleven_flash_v2_5"


def elevenlabs_tts(**kwargs) -> elevenlabs.TTS:
    """The one place an ElevenLabs TTS gets built, with the API key passed
    explicitly from config (which accepts ELEVENLABS_API_KEY as documented,
    or the plugin's own ELEVEN_API_KEY)."""
    kwargs.setdefault("model", ELEVENLABS_MODEL)
    if config.ELEVENLABS_API_KEY:
        kwargs.setdefault("api_key", config.ELEVENLABS_API_KEY)
    return elevenlabs.TTS(**kwargs)

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


class RouterLLM(llm.LLM):
    """A stand-in LLM that is never called. livekit-agents (1.8.4) only
    answers a finished user turn when *some* LLM is configured — in
    `AgentActivity._user_turn_completed_impl`: `elif self.llm is None:
    return  # skip response if no llm is set` — and `generate_reply()`
    raises without one. With no `llm=` at all, a real call would play the
    greeting and then never reply again (found by D12's scripted call).
    OrchestratorAgent.llm_node() replaces the model call entirely, so
    this object only has to exist: `chat()` raising is the proof nothing
    ever reaches it."""

    @property
    def model(self) -> str:
        return "voice-orchestrator-router"

    @property
    def provider(self) -> str:
        return "voice-orchestrator"

    def chat(self, **kwargs):  # type: ignore[override]
        raise RuntimeError("RouterLLM.chat() is never called: OrchestratorAgent.llm_node() replaces the model")


class OrchestratorAgent(Agent):
    """One instance per LiveKit job (= one phone call). `bridge` already
    carries its own `CallSession`, so this class itself stays stateless —
    all per-call state lives in the bridge, the same separation
    orchestrator.py keeps between its (stateless) routing/tool functions
    and the (stateful) CallSession object they're handed."""

    def __init__(
        self,
        bridge: VoiceBridge,
        instructions: str = "",
        voice_factory: "Callable[[AgentSpec], tts.TTS] | None" = None,
    ) -> None:
        super().__init__(instructions=instructions or _DEFAULT_INSTRUCTIONS, llm=RouterLLM())
        self._bridge = bridge
        # How an agent's voice override becomes a TTS instance. None = the
        # real ElevenLabs one below; tests pass a fake, the live check wraps
        # the real one to record which voice synthesized what.
        self._voice_factory = voice_factory
        # Per-agent ElevenLabs TTS instances (blocco 2, fixes D1), cached by
        # (voice_id, stability, speed) — elevenlabs.TTS() doesn't open a
        # network connection at construction time, so this just avoids
        # rebuilding the Python object on every single turn.
        self._tts_cache: dict[tuple[str, float | None, float | None], tts.TTS] = {}
        # The TTS the pipeline is currently set to; None = the session's
        # default (worker.py), which is also the starting state.
        self._active_tts: tts.TTS | None = None
        self._hangup_scheduled = False
        # Set by tests / the live check to observe the hangup instead of
        # deleting a room; see _end_call().
        self.ended_at: float | None = None
        # Blocco 7, fase C: every event published to the browser, in order
        # (the call page builds its live timeline from these; tests read
        # them here). See call_events.py for the shapes.
        self.events: list[dict] = []
        self._turn_seq = 0

    def _tts_for_agent(self, agent: AgentSpec) -> tts.TTS | None:
        """None when the agent has no voice_id override — apply_voice()
        then goes back to the TTS AgentSession was built with in worker.py."""
        if not agent.voice_id:
            return None
        key = (agent.voice_id, agent.voice_stability, agent.voice_speed)
        cached = self._tts_cache.get(key)
        if cached is not None:
            return cached
        if self._voice_factory is not None:
            voice = self._voice_factory(agent)
            self._tts_cache[key] = voice
            return voice
        extra: dict = {}
        if agent.voice_stability is not None or agent.voice_speed is not None:
            settings_kwargs: dict = {
                "stability": agent.voice_stability if agent.voice_stability is not None else 0.5,
                "similarity_boost": 0.75,
            }
            if agent.voice_speed is not None:
                settings_kwargs["speed"] = agent.voice_speed
            extra["voice_settings"] = elevenlabs.VoiceSettings(**settings_kwargs)
        voice = elevenlabs_tts(voice_id=agent.voice_id, **extra)
        self._tts_cache[key] = voice
        return voice

    def apply_voice(self, agent: AgentSpec | None) -> None:
        """Point the pipeline at `agent`'s voice (or back at the session's
        default if it has none) — a no-op when it's already the right one,
        so calling it on every turn costs nothing until a handoff actually
        changes the voice. Must run before the reply's text reaches
        tts_node: llm_node calls it before yielding, worker.py before the
        root's first_message."""
        target = self._tts_for_agent(agent) if agent else None
        if target is self._active_tts:
            return
        # update_options(tts=...) wires metrics/error handlers and prewarms
        # the new TTS; the session's own instance stands for "no override".
        self.update_options(tts=target if target is not None else self.session.tts)
        self._active_tts = target

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
        from_agent_id = self._bridge.session.current_agent_id or self._bridge.root.id
        result = await asyncio.to_thread(self._bridge.turn, utterance)
        self._turn_seq += 1
        await self.publish(
            call_events.turn_event(
                self._bridge.root,
                from_agent_id,
                utterance,
                result,
                self._bridge.session,
                self._turn_seq,
                simulated=isinstance(self._bridge.provider, FakeProvider),
            )
        )
        # Voice of whoever answered *this* turn — after handle_turn(), so a
        # handoff in this very turn already speaks with the new agent's voice.
        self.apply_voice(result.agent)
        # Built-in `end_call` tool (blocco 2): handle_turn() just sets this
        # slot, same mechanism as transfer_to_human's `transferred` flag —
        # the actual hangup is a voice-layer concern, so it lives here.
        # The handle is taken now, while this reply is the current speech.
        if self._bridge.session.slots.get("call_ended") and not self._hangup_scheduled:
            self._hangup_scheduled = True
            speech = self.session.current_speech
            asyncio.create_task(self._hang_up_after_speaking(speech, result.reply))
        if result.reply:
            yield result.reply

    async def _hang_up_after_speaking(self, speech, reply: str) -> None:
        """Ends the call once the farewell has actually finished playing:
        `SpeechHandle.wait_for_playout()` resolves when the audio output
        reports the segment played out (D12 — this used to be a word-count
        guess). Bounded by a timeout so a stuck output can't keep a call
        open forever; falls back to the old estimate only if there is no
        speech handle at all."""
        budget = max(10.0, len(reply.split()) * 1.0)
        if speech is not None:
            try:
                await asyncio.wait_for(speech.wait_for_playout(), timeout=budget)
            except asyncio.TimeoutError:
                pass
        else:
            await asyncio.sleep(max(1.5, len(reply.split()) * 0.35))
        await self._end_call()

    async def _end_call(self) -> None:
        """In a real job, deleting the room disconnects the caller and ends
        the job (worker.py's shutdown callback then logs the call). Outside a
        job (tests, scripts/d12_live_check.py) there's no room: just close
        the session."""
        self.ended_at = asyncio.get_running_loop().time()
        await self.publish(call_events.ended_event("end_call"))
        ctx = get_job_context(required=False)
        if ctx is not None:
            await ctx.delete_room()
        else:
            self.session.shutdown(drain=True)

    async def publish(self, event: dict) -> None:
        """Sends one call event to everyone in the room on the data channel
        (topic call_events.EVENTS_TOPIC), reliably and in order. Outside a
        job (tests, the scripted harness) there is no room: the event is only
        kept in `self.events`. Never fails the call — a lost event costs a
        line in the live view, not the conversation."""
        self.events.append(event)
        ctx = get_job_context(required=False)
        if ctx is None:
            return
        try:
            await ctx.room.local_participant.publish_data(
                json.dumps(event).encode("utf-8"), reliable=True, topic=call_events.EVENTS_TOPIC
            )
        except Exception:  # noqa: BLE001 — see docstring
            logging.getLogger(__name__).warning("could not publish call event %s", event.get("type"), exc_info=True)

