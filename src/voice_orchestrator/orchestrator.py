"""Ties one turn together: route → (maybe hand off) → run triggered tools →
compose a reply → condense memory. This is the only place that talks to
routing, tools, memory, and the LLM provider all at once — everything else
in the package is a focused, independently-testable piece.
"""
from __future__ import annotations

from dataclasses import dataclass

from .agents.registry import AgentSpec
from .llm import LLMProvider
from .memory import maybe_condense
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


def handle_turn(session: CallSession, root: AgentSpec, utterance: str, provider: LLMProvider) -> TurnResult:
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
        session.agent_path.append(target.id)
        current = target

    tool_notes: list[str] = []
    tool_ids_used: list[str] = []
    for tool_id in current.tools:
        tool = get_tool(tool_id)
        if tool.should_trigger(current, utterance, session):
            result = tool.run(current, utterance, session)
            tool_notes.append(result.summary)
            tool_ids_used.append(tool_id)

    reply = provider.respond(
        agent=current,
        utterance=utterance,
        context_summary=session.rolling_summary,
        recent_turns=session.last_turns(2),
        tool_notes=tool_notes,
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
