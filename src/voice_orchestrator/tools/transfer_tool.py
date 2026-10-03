"""Simulated call transfer — the "backend capability" integration shape
(no external network call, just session-state mutation the orchestrator
acts on: end the automated turn, hand the call to a human queue)."""
import re

from ..agents.registry import AgentSpec
from ..state import CallSession
from .base import Tool, ToolResult

TRIGGERS = [
    "operatore", "operatrice", "persona vera", "essere umano", "parlare con qualcuno",
    "trasferisc", "voglio un umano", "non capisci", "fammi parlare con",
]


class TransferToHumanTool(Tool):
    id = "transfer_to_human"
    description = "Escalates the call to a human agent queue."

    def should_trigger(self, agent: AgentSpec, utterance: str, session: CallSession) -> bool:
        text = utterance.lower()
        return any(re.search(re.escape(t), text) for t in TRIGGERS)

    def run(self, agent: AgentSpec, utterance: str, session: CallSession) -> ToolResult:
        session.slots["transferred"] = True
        session.slots["transfer_reason"] = utterance
        session.slots["transfer_from_agent"] = agent.id
        return ToolResult(
            summary=(
                "The call has been escalated to a human agent queue. Tell the caller, "
                "briefly and reassuringly, that a human colleague will take over shortly, "
                "and that everything discussed so far (summarize `handoff_summary` if given) "
                "has already been passed along so they won't have to repeat themselves."
            ),
            data={"transferred": True, "escalated_from": agent.id},
        )
