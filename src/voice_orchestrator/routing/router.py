"""The router proper: combines the two cheap levels (gate, classifier) and
only falls through to an LLM call when both of them genuinely can't decide.

Three possible outcomes per turn, in increasing order of cost:
  1. "gate_only"   — the gate left exactly one eligible candidate, no need to
                      even run the classifier.
  2. "pattern"      — the classifier found an unambiguous keyword winner among
                      the eligible candidates.
  3. "llm_fallback" — both of the above were ambiguous; the conversational
                      LLM is asked to pick, with the option to just "stay".

Staying with the current agent is always a valid outcome — this is what
keeps the system from ping-ponging between agents when nothing in the
utterance actually calls for a handoff.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from ..agents.registry import AgentSpec
from ..state import CallSession, RoutingEvent
from . import gate
from .classifier import classify

STAY = "__stay__"

# Signature: (utterance, candidate_agents, current_agent_id, session) -> chosen_agent_id (or STAY)
LLMFallback = Callable[[str, list[AgentSpec], str, CallSession], str]


@dataclass
class RoutingDecision:
    chosen_agent_id: str  # may equal current_agent.id, meaning "stay"
    resolved_by: str
    eligible_agents: list[str]
    reason: str = ""


def _build_context(session: CallSession) -> dict:
    context = dict(session.slots)
    context["depth"] = session.depth
    context.setdefault("authenticated", session.slots.get("authenticated", False))
    return context


def route(
    utterance: str,
    current_agent: AgentSpec,
    session: CallSession,
    llm_fallback: LLMFallback | None = None,
) -> RoutingDecision:
    start = time.perf_counter()
    context = _build_context(session)

    eligible = [c for c in current_agent.children if gate.is_eligible(c.eligibility, context)]
    eligible_ids = [a.id for a in eligible]

    if not eligible:
        decision = RoutingDecision(
            chosen_agent_id=current_agent.id,
            resolved_by="gate_only",
            eligible_agents=eligible_ids,
            reason="no eligible children — staying with current agent",
        )
        _record(session, utterance, decision, start)
        return decision

    if len(eligible) == 1:
        decision = RoutingDecision(
            chosen_agent_id=eligible[0].id,
            resolved_by="gate_only",
            eligible_agents=eligible_ids,
            reason="only one eligible candidate",
        )
        _record(session, utterance, decision, start)
        return decision

    result = classify(utterance, eligible)
    if result.agent_id is not None:
        decision = RoutingDecision(
            chosen_agent_id=result.agent_id,
            resolved_by="pattern",
            eligible_agents=eligible_ids,
            reason=f"keyword scores={result.scores}",
        )
        _record(session, utterance, decision, start)
        return decision

    if llm_fallback is None:
        decision = RoutingDecision(
            chosen_agent_id=current_agent.id,
            resolved_by="llm_fallback",
            eligible_agents=eligible_ids,
            reason="ambiguous and no LLM fallback configured — staying put",
        )
        _record(session, utterance, decision, start)
        return decision

    chosen = llm_fallback(utterance, eligible, current_agent.id, session)
    chosen_id = chosen if chosen in eligible_ids else current_agent.id
    decision = RoutingDecision(
        chosen_agent_id=chosen_id,
        resolved_by="llm_fallback",
        eligible_agents=eligible_ids,
        reason=f"classifier ambiguous (scores={result.scores}), LLM chose {chosen_id!r}",
    )
    _record(session, utterance, decision, start)
    return decision


def _record(session: CallSession, utterance: str, decision: RoutingDecision, start: float) -> None:
    elapsed_ms = (time.perf_counter() - start) * 1000
    session.record_routing(
        RoutingEvent(
            utterance=utterance,
            resolved_by=decision.resolved_by,
            chosen_agent=decision.chosen_agent_id,
            eligible_agents=decision.eligible_agents,
            latency_ms=elapsed_ms,
            reason=decision.reason,
        )
    )
