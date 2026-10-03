"""In-process call state. Per the architecture research: a single call is a
single process, so a shared Python object is the right level of complexity —
no Redis, no external store. (Redis would earn its place once the family
runs as separate processes and needs cross-process pub/sub — see README.)

The full transcript is kept here for logging/eval, but routing and handoffs
deliberately do NOT see all of it — see memory.py for the scoped views.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Turn:
    speaker: str  # "caller" | "agent"
    agent_id: str | None  # which agent produced this turn, if speaker == "agent"
    text: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class RoutingEvent:
    utterance: str
    resolved_by: str  # "gate_only" | "pattern" | "llm_fallback"
    chosen_agent: str | None
    eligible_agents: list[str]
    latency_ms: float
    reason: str = ""


@dataclass
class HandoffEvent:
    from_agent: str
    to_agent: str
    reason: str


@dataclass
class CallSession:
    call_id: str
    turns: list[Turn] = field(default_factory=list)  # active window — condensed by memory.maybe_condense
    full_log: list[Turn] = field(default_factory=list)  # never truncated — for export/eval/debugging only
    slots: dict[str, Any] = field(default_factory=dict)
    rolling_summary: str = ""
    agent_path: list[str] = field(default_factory=list)  # root -> ... -> current
    routing_log: list[RoutingEvent] = field(default_factory=list)
    handoff_log: list[HandoffEvent] = field(default_factory=list)

    @property
    def current_agent_id(self) -> str | None:
        return self.agent_path[-1] if self.agent_path else None

    @property
    def depth(self) -> int:
        return len(self.agent_path)

    def add_turn(self, speaker: str, text: str, agent_id: str | None = None) -> None:
        turn = Turn(speaker=speaker, agent_id=agent_id, text=text)
        self.turns.append(turn)
        self.full_log.append(turn)

    def last_turns(self, n: int = 2) -> list[Turn]:
        return self.turns[-n:]

    def record_routing(self, event: RoutingEvent) -> None:
        self.routing_log.append(event)

    def record_handoff(self, from_agent: str, to_agent: str, reason: str) -> None:
        self.handoff_log.append(HandoffEvent(from_agent=from_agent, to_agent=to_agent, reason=reason))

    def routing_stats(self) -> dict[str, int]:
        """How many routing decisions were resolved at each level — the number
        that actually demonstrates the latency story (most should be gate_only
        or pattern, not llm_fallback)."""
        stats = {"gate_only": 0, "pattern": 0, "llm_fallback": 0}
        for event in self.routing_log:
            stats[event.resolved_by] = stats.get(event.resolved_by, 0) + 1
        return stats
