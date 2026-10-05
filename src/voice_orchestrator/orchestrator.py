"""Ties one turn together: route → (maybe hand off) → run triggered tools →
compose a reply → condense memory. This is the only place that talks to
routing, tools, memory, and the LLM provider all at once — everything else
in the package is a focused, independently-testable piece.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable  # noqa: F401  (used in a string annotation)

from . import observability
from .agents.registry import AgentSpec
from .llm import LLMProvider, get_provider_for_agent
from .memory import maybe_condense
from .routing import gate
from .routing.router import RoutingDecision, route
from .state import CallSession, Turn
from .tools import get_tool


@dataclass
class TurnResult:
    reply: str
    agent: AgentSpec
    routing: RoutingDecision
    handed_off: bool
    tool_ids_used: list[str]


def _ensure_started(session: CallSession, root: AgentSpec) -> None:
    if not session.agent_path:
        session.agent_path = [root.id]


def handle_turn(
    session: CallSession,
    root: AgentSpec,
    utterance: str,
    provider: LLMProvider,
    responder: "Callable[[AgentSpec], tuple[LLMProvider, float | None]] | None" = None,
) -> TurnResult:
    """`provider` routes (the LLM level) and condenses the history.
    `responder` picks the provider (and temperature) that writes the
    answering agent's reply (blocco 8: the project's default LLM or the
    agent's override, see project.py); None keeps the blocco-2 rule, get_provider_for_agent().
    The test endpoints pass one that always returns FakeProvider for
    visitors, so an agent with its own model never spends tokens on them."""
    _ensure_started(session, root)
    session.add_turn("caller", utterance)

    current = root.find(session.current_agent_id)
    assert current is not None, f"agent_path points at an unknown agent: {session.agent_path}"

    decision = route(
        utterance,
        current,
        session,
        llm_fallback=lambda u, candidates, cur_id, s: provider.classify(u, candidates, cur_id, s),
    )

    handed_off = decision.chosen_agent_id != current.id
    if handed_off:
        target = root.find(decision.chosen_agent_id)
        assert target is not None
        session.record_handoff(from_agent=current.id, to_agent=target.id, reason=decision.reason)
        session.record_event(
            observability.COMPONENT_AGENT,
            observability.EVENT_HANDOFF,
            from_agent=current.id,
            to_agent=target.id,
            reason=decision.reason,
        )
        session.agent_path.append(target.id)
        current = target

    tool_notes: list[str] = []
    caller_notes: list[str] = []
    tool_ids_used: list[str] = []
    gate_context = session.gate_context()
    for binding in current.tools:
        # Same AST-safe gate as agent eligibility, just scoped to one tool —
        # e.g. "channel == 'voice'" keeps a tool off a text/SMS turn. An empty
        # condition (the common case) is always eligible, so this is a no-op
        # for every tool that doesn't declare one.
        if not gate.is_eligible(binding.condition, gate_context):
            session.record_event(
                observability.COMPONENT_TOOL,
                observability.EVENT_TOOL_SKIPPED_CONDITION,
                tool_id=binding.id,
                agent_id=current.id,
                condition=binding.condition,
            )
            continue
        tool = get_tool(binding.id)
        if tool.should_trigger(current, utterance, session):
            result = tool.run(current, utterance, session)
            tool_notes.append(result.summary)
            caller_notes.append(result.caller_note)
            tool_ids_used.append(binding.id)
            session.record_event(
                observability.COMPONENT_TOOL,
                observability.EVENT_TOOL_TRIGGERED,
                tool_id=binding.id,
                agent_id=current.id,
            )

    # Blocco 2: an agent can override which LLM composes *its* reply
    # (AgentSpec.llm_provider/llm_model/llm_temperature) — `provider` here
    # stays the call's own default/fallback, used as-is for classify()
    # above (routing shouldn't vary per destination agent) and for
    # summarize() below (it condenses the whole call, not one agent's
    # turn). Only respond() is agent-specific.
    if responder:
        reply_provider, temperature = responder(current)
    else:
        reply_provider, temperature = get_provider_for_agent(current, default=provider), current.llm_temperature
    reply = reply_provider.respond(
        agent=current,
        utterance=utterance,
        context_summary=session.rolling_summary,
        recent_turns=session.last_turns(2),
        tool_notes=tool_notes,
        temperature=temperature,
        caller_notes=caller_notes,
    )
    session.add_turn("agent", reply, agent_id=current.id)

    # Conceptually off the latency-critical path: condensing is bookkeeping for
    # the *next* turn, not this one, so in a real streaming system this call
    # would be dispatched in the background right after the reply above starts
    # playing, not awaited before returning. This CLI demo is synchronous, so
    # it still runs inline here — the separation that matters (not blocking the
    # reply the caller actually waits on) only shows up once there's real
    # audio I/O to overlap it with.
    maybe_condense(session, summarizer=provider.summarize)

    return TurnResult(
        reply=reply,
        agent=current,
        routing=decision,
        handed_off=handed_off,
        tool_ids_used=tool_ids_used,
    )
