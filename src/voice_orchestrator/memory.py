"""Scoped memory views — the answer to "how much should the router vs. a
specialist agent see?" from the architecture research (Coval's hierarchical
split: critical info persists fully, working info stays temporary, historical
info gets compressed). Nobody downstream ever gets the raw, ever-growing
transcript; they get one of the views built here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import observability
from .state import CallSession, Turn

ROLLING_SUMMARY_TRIGGER = 6  # once the transcript passes this many turns, condense it
KEEP_VERBATIM_TURNS = 2  # how many most-recent turns always stay verbatim


@dataclass
class RouterView:
    """What the router sees to make a routing decision: NOT the full transcript."""

    rolling_summary: str
    recent_turns: list[Turn]
    slots: dict[str, Any]


@dataclass
class HandoffPackage:
    """What a specialist agent receives when the router (or another specialist)
    hands off to it — a structured package, not "everything the router saw"."""

    from_agent: str
    reason: str
    slots: dict[str, Any]
    summary: str
    recent_turns: list[Turn]


def router_view(session: CallSession) -> RouterView:
    return RouterView(
        rolling_summary=session.rolling_summary,
        recent_turns=session.last_turns(KEEP_VERBATIM_TURNS),
        slots=dict(session.slots),
    )


def build_handoff_package(session: CallSession, from_agent: str, reason: str) -> HandoffPackage:
    return HandoffPackage(
        from_agent=from_agent,
        reason=reason,
        slots=dict(session.slots),
        summary=session.rolling_summary,
        recent_turns=session.last_turns(KEEP_VERBATIM_TURNS),
    )


def maybe_condense(session: CallSession, summarizer) -> None:
    """Folds older turns into `rolling_summary` once the transcript gets long,
    so neither the router nor a handoff package ever has to replay a
    linearly-growing transcript. `summarizer` is a callable
    (previous_summary, turns_to_fold) -> new_summary — in FakeProvider mode
    this is a cheap truncation; with a real LLM provider it's an actual
    summarization call, done OFF the latency-critical turn (see orchestrator.py)."""
    if len(session.turns) <= ROLLING_SUMMARY_TRIGGER:
        return
    to_fold = session.turns[: -KEEP_VERBATIM_TURNS]
    if not to_fold:
        return
    session.rolling_summary = summarizer(session.rolling_summary, to_fold)
    # Keep only the verbatim tail; everything older is now represented by the summary.
    session.turns = session.turns[-KEEP_VERBATIM_TURNS:]
    session.record_event(observability.COMPONENT_MEMORY, observability.EVENT_MEMORY_CONDENSED, turns_folded=len(to_fold))
