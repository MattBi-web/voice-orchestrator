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
from ..project import stt_for, tts_for
from .providers import choice_key, make_stt, make_tts
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

# Blocco 9 (1.1): LiveKit's preemptive generation starts the reply before the
# caller's turn is confirmed and throws it away if they keep talking. For a
# plain LLM that only costs tokens; here llm_node runs a whole orchestrator
# turn, which records the utterance in CallSession, runs tools (webhooks,
# transfer_to_human, end_call) and publishes a turn event. A discarded
# speculative turn would leave all of that behind: a duplicated or truncated
# caller line, a webhook fired twice, a hangup scheduled for a sentence the
# caller hadn't finished. So it's off, for every session (worker and the
# test harness). Cost: the reply starts after end-of-turn instead of during
# it, a few hundred ms. Turning it back on needs a two-phase turn (route
# without side effects first, run tools and commit only once the turn is
# confirmed) — see docs/ROADMAP.md, blocco 9.
TURN_HANDLING = {"preemptive_generation": {"enabled": False}}

_DEFAULT_INSTRUCTIONS = (
    "Voice orchestrator — this agent's replies are produced entirely by "
    "voice_orchestrator's own router/tools/memory stack (see bridge.py and "
    "orchestrator.py), not by an LLM reading these instructions. This text "
    "exists only because LiveKit's Agent base class requires some "
    "`instructions` string at construction time."
)


def _overrides_tts(agent: AgentSpec) -> bool:
    return bool(agent.tts_provider or agent.tts_model or agent.voice_id or agent.voice_stability is not None or agent.voice_speed is not None)


def _overrides_stt(agent: AgentSpec) -> bool:
    return bool(agent.stt_provider or agent.stt_model or agent.stt_language)


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
        # Blocco 8: TTS and STT instances per resolved choice (project
        # default or agent override, project.py), built once and reused.
        self._tts_cache: dict[tuple, tts.TTS] = {}
        self._stt_cache: dict[tuple, object] = {}
        # What the session was started with (worker.py: the root agent's
        # pipeline); an agent resolving to the same choice uses the session's
        # own instance. None until worker.py/the harness sets it.
        self.default_tts_key: tuple | None = None
        self.default_stt_key: tuple | None = None
        # The TTS/STT the pipeline is currently set to; None = the session's.
        self._active_tts: tts.TTS | None = None
        self._active_stt: object | None = None
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
        """None when the agent's resolved TTS is the one the session started
        with (worker.py) — apply_voice() then goes back to the session's own
        instance. Otherwise the agent's own, from its override or the
        project default (blocco 8)."""
        choice = tts_for(agent, self._bridge.settings)
        key = choice_key(choice)
        if key == self.default_tts_key or (self.default_tts_key is None and not _overrides_tts(agent)):
            return None
        cached = self._tts_cache.get(key)
        if cached is None:
            cached = self._voice_factory(agent) if self._voice_factory is not None else make_tts(choice)
            self._tts_cache[key] = cached
        return cached

    def _stt_for_agent(self, agent: AgentSpec) -> object | None:
        choice = stt_for(agent, self._bridge.settings)
        key = choice_key(choice)
        if key == self.default_stt_key or (self.default_stt_key is None and not _overrides_stt(agent)):
            return None
        cached = self._stt_cache.get(key)
        if cached is None:
            cached = make_stt(choice)
            self._stt_cache[key] = cached
        return cached

    def apply_voice(self, agent: AgentSpec | None) -> None:
        """Point the pipeline at `agent`'s TTS and STT (or back at the
        session's defaults) — a no-op when they're already the right ones,
        so calling it on every turn costs nothing until a handoff changes
        something. Must run before the reply's text reaches tts_node:
        llm_node calls it before yielding, worker.py before the root's
        first_message. STT applies from the caller's next utterance."""
        target = self._tts_for_agent(agent) if agent else None
        if target is not self._active_tts:
            # update_options(tts=...) wires metrics/error handlers and
            # prewarms the new TTS; the session's own instance stands for
            # "no override".
            self.update_options(tts=target if target is not None else self.session.tts)
            self._active_tts = target
            logging.getLogger(__name__).info("pipeline: %s speaks with %s", agent.id if agent else "-", tts_for(agent, self._bridge.settings).as_dict() if agent else "default")
        listener = self._stt_for_agent(agent) if agent else None
        if listener is not self._active_stt:
            self.update_options(stt=listener if listener is not None else self.session.stt)
            self._active_stt = listener
            logging.getLogger(__name__).info("pipeline: %s listens with %s", agent.id if agent else "-", stt_for(agent, self._bridge.settings).as_dict() if agent else "default")

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
                simulated=self._bridge.is_simulated(result.agent),
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

