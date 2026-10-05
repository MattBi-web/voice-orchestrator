"""Live call events (blocco 7, fase C): what the browser needs to show a
call as it happens — which agent answered each turn, which router level
decided it and why, which tools ran, what was said.

Plain dicts, built here in the core with no livekit import, so they can be
tested on their own; voice/agent.py publishes them on the LiveKit room's
data channel (topic EVENTS_TOPIC) and the call page renders them. The
explanation mirrors the Overview's router demo: the gate's closed agents
with their rule, the keyword that matched, whether the turn stayed put.
"""
from __future__ import annotations

from typing import Any

from .agents.registry import AgentSpec
from .orchestrator import TurnResult
from .state import CallSession

EVENTS_TOPIC = "vo.events"


def _find(root: AgentSpec, agent_id: str | None) -> AgentSpec | None:
    return root.find(agent_id) if agent_id else None


def greeting_event(root: AgentSpec, text: str) -> dict[str, Any]:
    return {"type": "greeting", "agent_id": root.id, "agent_name": root.name, "text": text}


def turn_event(
    root: AgentSpec,
    from_agent_id: str,
    utterance: str,
    result: TurnResult,
    session: CallSession,
    seq: int,
    simulated: bool = False,
) -> dict[str, Any]:
    """One caller turn, explained. `from_agent_id` is the agent that had the
    call when the caller spoke (the router looks at its specialists).
    `simulated`: no language model behind this call (FakeProvider), so an
    LLM-level decision and the reply are the demo's scripted stand-ins; the
    page says so instead of passing them off as a model's."""
    decision = result.routing
    from_agent = _find(root, from_agent_id)
    children = from_agent.children if from_agent else []
    eligible = set(decision.eligible_agents)
    excluded = [{"id": c.id, "name": c.name, "rule": c.eligibility} for c in children if c.id not in eligible]

    lowered = utterance.lower()
    keyword = None
    if decision.resolved_by == "pattern":
        keyword = next((t for t in result.agent.triggers if t.lower() in lowered), None)

    latency = session.routing_log[-1].latency_ms if session.routing_log else None
    return {
        "type": "turn",
        "seq": seq,
        "caller": utterance,
        "from_agent_id": from_agent_id,
        "from_agent_name": from_agent.name if from_agent else from_agent_id,
        "agent_id": result.agent.id,
        "agent_name": result.agent.name,
        "resolved_by": decision.resolved_by,
        "eligible": list(decision.eligible_agents),
        "excluded": excluded,
        "keyword": keyword,
        "handed_off": result.handed_off,
        "tools": list(result.tool_ids_used),
        "reply": result.reply,
        "latency_ms": round(latency, 2) if latency is not None else None,
        "simulated": simulated,
    }


def ended_event(reason: str) -> dict[str, Any]:
    return {"type": "ended", "reason": reason}
