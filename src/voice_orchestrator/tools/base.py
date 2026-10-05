"""Pluggable tools an agent can be given access to (via its `tools:` list in
agents.yaml). Two integration shapes, both expressed through the same
interface: an external API call (CheckAccountStatusTool mocks one) and a
backend capability like RAG (KnowledgeLookupTool) or call transfer
(TransferToHumanTool).

Deliberately NOT native provider function-calling: that would mean a
different mechanism per LLM provider (and none at all in FakeProvider mode),
which breaks the "runs with zero API keys" requirement. Instead each tool
decides for itself, from the utterance and session state, whether it's
relevant (`should_trigger`) — a simple, provider-agnostic mechanism. Swapping
this for native tool_use (Anthropic, OpenAI, Gemini all support it) is a
drop-in replacement once you've picked one provider to commit to.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..agents.registry import AgentSpec
from ..state import CallSession


@dataclass
class ToolResult:
    summary: str  # short, LLM-ready grounding text to fold into the reply
    data: dict[str, Any] = field(default_factory=dict)
    # What to say to the caller when no LLM composes the reply (FakeProvider)
    # — D10. `summary` is written *for an LLM* and can be an instruction
    # ("Tell the caller, briefly…"): fine as grounding, wrong as a reply read
    # out verbatim. A tool whose summary is plain data (an account balance, a
    # KB passage) can leave this as None and the summary is used as-is; a tool
    # whose summary is an instruction sets the caller-facing line here — and
    # "" means "say nothing to the caller", not "fall back to the summary".
    caller_text: str | None = None

    @property
    def caller_note(self) -> str:
        return self.summary if self.caller_text is None else self.caller_text


class Tool(ABC):
    id: str
    description: str

    @abstractmethod
    def should_trigger(self, agent: AgentSpec, utterance: str, session: CallSession) -> bool: ...

    @abstractmethod
    def run(self, agent: AgentSpec, utterance: str, session: CallSession) -> ToolResult: ...
