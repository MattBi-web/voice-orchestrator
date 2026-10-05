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
from dataclasses import dataclass, field
from typing import Any

from .. import config
from ..agents.registry import AgentSpec, load_family_file
from ..llm import FakeProvider, LLMProvider, ResilientProvider
from ..orchestrator import TurnResult, handle_turn
from ..project import DEFAULT_PROJECT, ModelSettings, responder, router_provider
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
    # Blocco 8: the project this call is on, and its default models. The
    # router and the replies resolve through project.py; `provider` stays
    # the router's (and the history summary's) provider.
    project_id: str = DEFAULT_PROJECT
    settings: ModelSettings = field(default_factory=ModelSettings)
    responder: Any = None

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
        return handle_turn(self.session, self.root, utterance.strip(), self.provider, responder=self.responder)

    def is_simulated(self, agent: AgentSpec) -> bool:
        """True when `agent`'s reply comes from no model (FakeProvider):
        the call page then labels it a placeholder."""
        if self.responder is not None:
            return isinstance(self.responder(agent)[0], FakeProvider)
        return isinstance(self.provider, FakeProvider)


logger = logging.getLogger(__name__)


def load_call_family(project_id: str = DEFAULT_PROJECT) -> tuple[AgentSpec, ModelSettings]:
    """The agent family a new call runs on. Shared mode (blocco 6): read
    fresh from the database at every call — what was saved in the builder a
    minute ago is what answers this call, with no export and no restart
    (closes D4) — and the tool registry is re-synced from the same database
    first, so MCP servers and webhook tools added in the builder are live
    too. Default mode: config/agents.yaml, as before. An empty database
    (the web service hasn't seeded it yet) falls back to the YAML rather
    than failing the call. Blocco 8: the project's family and its default
    models; the YAML's `project:` block carries the models in default mode."""
    if config.shared_mode():
        from ..webapi import db, mcp_sync, project_repository, repository, webhook_sync

        with db.session_scope() as s:
            mcp_sync.sync_registry_from_db(s)
            webhook_sync.sync_registry_from_db(s)
            root = repository.build_tree(s, project_id)
            settings = project_repository.settings_of(s, project_id)
        if root is not None:
            return root, settings
        logger.warning("shared mode: project %r has no agents, using %s", project_id, config.AGENTS_FILE)
    root, meta = load_family_file(config.AGENTS_FILE)
    return root, ModelSettings.from_dict(meta.get("settings"))


def new_voice_bridge(call_id: str, provider: LLMProvider | None = None, project_id: str = DEFAULT_PROJECT) -> VoiceBridge:
    """What worker.py's entrypoint calls once per LiveKit job — one bridge
    per phone call, on the family `load_call_family()` resolves (the
    database in shared mode, config/agents.yaml otherwise) and the same
    VOICE_ORCH_PROVIDER env var the CLI uses. channel="voice" is the
    default CallSession already has, but set explicitly here so an agent's
    `channel == 'voice'`-gated tools behave the same whether the call came
    in through this real voice layer or through `voice-orchestrator chat
    --channel voice`."""
    root, settings = load_call_family(project_id)
    session = CallSession(call_id=call_id, channel="voice")
    if provider is not None:
        # A provider passed in (tests) routes and answers.
        return VoiceBridge(
            session=session,
            root=root,
            provider=provider,
            project_id=project_id,
            settings=settings,
            responder=lambda agent: (provider, agent.llm_temperature),
        )
    # Otherwise the project's router model, and each agent's reply from the
    # project's LLM or its own override — wrapped so a failing model costs
    # the caller one apology, not a silent call (llm.ResilientProvider).
    pick = responder(settings)

    def resilient(agent: AgentSpec):
        inner, temperature = pick(agent)
        return (inner if isinstance(inner, FakeProvider) else _resilient(inner)), temperature

    return VoiceBridge(
        session=session,
        root=root,
        provider=_resilient(router_provider(settings)),
        project_id=project_id,
        settings=settings,
        responder=resilient,
    )


_wrapped: dict[int, ResilientProvider] = {}


def _resilient(inner: LLMProvider) -> LLMProvider:
    if isinstance(inner, FakeProvider):
        return inner
    return _wrapped.setdefault(id(inner), ResilientProvider(inner))
