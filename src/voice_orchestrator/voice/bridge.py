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

import logging
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


logger = logging.getLogger(__name__)


def load_call_family() -> AgentSpec:
    """The agent family a new call runs on. Shared mode (blocco 6): read
    fresh from the database at every call — what was saved in the builder a
    minute ago is what answers this call, with no export and no restart
    (closes D4) — and the tool registry is re-synced from the same database
    first, so MCP servers and webhook tools added in the builder are live
    too. Default mode: config/agents.yaml, as before. An empty database
    (the web service hasn't seeded it yet) falls back to the YAML rather
    than failing the call."""
    if config.shared_mode():
        from ..webapi import db, mcp_sync, repository, webhook_sync

        with db.session_scope() as s:
            mcp_sync.sync_registry_from_db(s)
            webhook_sync.sync_registry_from_db(s)
            root = repository.build_tree(s)
        if root is not None:
            return root
        logger.warning("shared mode: no agents in the database yet, using %s", config.AGENTS_FILE)
    return load_family(config.AGENTS_FILE)


def new_voice_bridge(call_id: str, provider: LLMProvider | None = None) -> VoiceBridge:
    """What worker.py's entrypoint calls once per LiveKit job — one bridge
    per phone call, on the family `load_call_family()` resolves (the
    database in shared mode, config/agents.yaml otherwise) and the same
    VOICE_ORCH_PROVIDER env var the CLI uses. channel="voice" is the
    default CallSession already has, but set explicitly here so an agent's
    `channel == 'voice'`-gated tools behave the same whether the call came
    in through this real voice layer or through `voice-orchestrator chat
    --channel voice`."""
    root = load_call_family()
    session = CallSession(call_id=call_id, channel="voice")
    return VoiceBridge(session=session, root=root, provider=provider or get_provider())
