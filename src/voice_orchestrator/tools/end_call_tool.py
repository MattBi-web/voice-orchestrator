"""Built-in `end_call` tool (blocco 2 — the ElevenLabs-platform equivalent
of their own `end_call` built-in). Same shape as transfer_tool.py: a
keyword trigger plus a session-state flag the voice layer acts on.

In the voice path, `voice/agent.py`'s `OrchestratorAgent.llm_node()` checks
`session.slots["call_ended"]` after speaking the reply and, if set,
disconnects the room shortly after — see that module's docstring for why
that's a heuristic, not an exact wait for the farewell to finish playing.
In the text/CLI path there's no room to disconnect: `chat()` just keeps
looping, which is fine — a human tester reads the goodbye and types 'exit'
themselves.
"""
import re

from ..agents.registry import AgentSpec
from ..state import CallSession
from .base import Tool, ToolResult

TRIGGERS = [
    "basta cos", "può chiudere", "puoi chiudere", "chiudi la chiamata", "chiudiamo qui",
    "nient'altro", "nient altro", "no grazie, basta", "va bene così, grazie", "arrivederci",
    "è tutto, grazie", "e tutto grazie",
]


class EndCallTool(Tool):
    id = "end_call"
    description = "Ends the call once the caller has nothing further to ask."

    def should_trigger(self, agent: AgentSpec, utterance: str, session: CallSession) -> bool:
        text = utterance.lower()
        return any(re.search(re.escape(t), text) for t in TRIGGERS)

    def run(self, agent: AgentSpec, utterance: str, session: CallSession) -> ToolResult:
        session.slots["call_ended"] = True
        return ToolResult(
            summary=(
                "The caller has nothing further. Say a brief, warm goodbye and nothing else — "
                "don't ask another question, don't offer more help."
            ),
            data={"call_ended": True},
        )
