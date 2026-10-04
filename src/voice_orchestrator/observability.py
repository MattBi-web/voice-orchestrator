"""Structured, per-step events — the adapted version of Rapida's
observability.RecordEvent system (their agentflow orchestrator emits
AgentTransitionMatched / AgentTransitionTriggered / AgentTransitionMissingEdge
at every graph step). Ours covers the same three kinds of step — a routing
decision, a handoff, a tool call — but stays in-process: each Event is
appended to CallSession.event_log, not shipped to an external telemetry
pipeline. Wiring a real sink (OpenTelemetry, a metrics backend) later is a
matter of iterating event_log, not changing how or where events get recorded.

Deliberately generalizes RoutingEvent (state.py) rather than replacing it:
RoutingEvent is the specific, stable record the routing eval depends on
(resolved_by, eligible_agents, latency_ms — see routing/router.py and
cli.py's `eval` command). Event is the broader trace alongside it — any
component (router, agent, tool, memory) can log one without state.py's
schema needing a new field for each of them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# Component names — mirrors Rapida's observability.Component* constants.
COMPONENT_ROUTER = "router"
COMPONENT_AGENT = "agent"
COMPONENT_TOOL = "tool"
COMPONENT_MEMORY = "memory"

# Event names — deliberately verbs/nouns, not level-of-detail-specific, so a
# future sink can group by (component, event) without knowing every field.
EVENT_ROUTING_DECISION = "routing_decision"
EVENT_HANDOFF = "handoff"
EVENT_TOOL_TRIGGERED = "tool_triggered"
EVENT_TOOL_SKIPPED_CONDITION = "tool_skipped_condition"
EVENT_MEMORY_CONDENSED = "memory_condensed"


@dataclass
class Event:
    component: str
    event: str
    attributes: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "event": self.event,
            "attributes": self.attributes,
            "occurred_at": self.occurred_at.isoformat(),
        }
