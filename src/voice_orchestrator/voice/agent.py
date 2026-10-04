"""LiveKit Agents integration — the only file in this project that imports
`livekit-agents`. All it does is: pull the latest caller utterance out of
the chat context LiveKit's session hands `llm_node()`, run it through the
*existing* text-core orchestrator via a `VoiceBridge`, and yield the reply
text back as the "LLM" output.

STT (Deepgram), VAD (Silero), and TTS (ElevenLabs) are configured once, in
worker.py, and never touched here. `llm_node` is the one extension point
this project needs: the router/tools/memory stack `orchestrator.py` already
has IS the "LLM" step for this agent — we're deliberately not calling a
real chat model at all (no `Agent.default.llm_node(...)` delegation, unlike
the override pattern LiveKit's own docs show for pre/post-processing a
model's output), because the whole thesis of this project is that a
deterministic router + scoped tools beats a general chat model deciding,
turn by turn, what to do. Letting a real LLM sit in this seat too would
just mean two different things arguing over who's driving the call.
"""
from __future__ import annotations

from typing import AsyncIterable

import asyncio

from livekit.agents import Agent, FunctionTool, ModelSettings, llm

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
