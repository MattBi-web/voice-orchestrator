"""The bridge between a real-time voice session and this project's existing
synchronous text-core orchestrator. No `livekit-agents` import here, on
purpose — this is the one piece of the voice layer a test can exercise
without `livekit-agents` (or any of its STT/TTS/VAD plugins) installed at
all, same zero-dependency-by-default ethos as the rest of this project.

`VoiceBridge` wraps exactly one phone call's worth of state: one
`CallSession`, one agent family (`root`), one LLM provider. `agent.py`'s
`OrchestratorAgent` holds one of these per LiveKit job and calls `.turn()`
once per caller utterance — the same `handle_turn()` call the CLI's
`chat()` loop makes, so a real voice call and a `voice-orchestrator chat`
session run through identical routing/handoff/tool/memory logic. The only
thing that differs between the two is where the utterance text comes from
(a live transcript vs. a REPL line) and where the reply text goes (TTS vs.
stdout) — both of those live in `agent.py`/`worker.py`, not here.
"""
from __future__ import annotations

from dataclasses import dataclass

from .. import config
from ..agents.registry import AgentSpec, load_family
from ..llm import LLMProvider, get_provider
from ..orchestrator import TurnResult, handle_turn
from ..state import CallSession


def is_actionable(utterance: str | None) -> bool:
    """False for empty/whitespace-only transcripts — the thing a VAD-driven
    STT pipeline occasionally hands you from background noise or a cough
    that got mis-segmented as speech. Kept as its own tiny function (rather
    than inlined in agent.py's llm_node) so it's testable without
    livekit-agents installed, and so a future non-LiveKit transport can
    reuse the exact same rule."""
    return bool(utterance and utterance.strip())


@dataclass
class VoiceBridge:
    """One of these per call. Construct via `new_voice_bridge()` in normal
    use — the bare dataclass is exposed mainly so tests can wire a
    `FakeProvider` straight in without touching config files."""

    session: CallSession
    root: AgentSpec
    provider: LLMProvider

    def turn(self, utterance: str) -> TurnResult:
        """One caller utterance in, one TurnResult out. `handle_turn()`
        itself is synchronous — same as every Tool in this project,
        including MCPTool, which internally calls `asyncio.run()`. A caller
        sitting inside an already-running asyncio event loop (agent.py's
        `llm_node`, which LiveKit drives) MUST NOT await this directly: run
        it on a thread via `asyncio.to_thread()`, or asyncio.run() will
        raise "cannot be called from a running event loop" the moment a
        turn happens to hit an MCP tool. That wrapping lives in agent.py,
        not here, so this method stays a plain, directly-testable function."""
        return handle_turn(self.session, self.root, utterance.strip(), self.provider)


def new_voice_bridge(call_id: str, provider: LLMProvider | None = None) -> VoiceBridge:
    """What worker.py's entrypoint calls once per LiveKit job — one bridge
    per phone call, loading the same config/agents.yaml family (and the
    same VOICE_ORCH_PROVIDER env var) the CLI uses. channel="voice" is the
    default CallSession already has, but set explicitly here so an agent's
    `channel == 'voice'`-gated tools behave the same whether the call came
    in through this real voice layer or through `voice-orchestrator chat
    --channel voice`."""
    root = load_family(config.AGENTS_FILE)
    session = CallSession(call_id=call_id, channel="voice")
    return VoiceBridge(session=session, root=root, provider=provider or get_provider())
