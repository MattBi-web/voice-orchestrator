"""The agent family is data, not code: every agent (and sub-agent, recursively)
is one entry in config/agents.yaml. Adding, removing, or re-parenting an agent
is a YAML edit (or a `voice-orchestrator agents add/remove` call) — never a
code change. This module just loads that YAML into typed, validated objects.
"""
from __future__ import annotations

import yaml
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ToolBinding:
    """One tool an agent may call, plus an optional per-tool eligibility
    condition — the adapted version of Rapida's per-tool source/mode/direction
    condition rules. Evaluated with the same AST-safe gate (routing/gate.py)
    used for agent eligibility, against CallSession.gate_context(), so a tool
    condition can combine the channel with any other slot
    ("channel == 'voice' and authenticated == true"), not just check one
    field at a time. Empty condition = always available, same convention as
    AgentSpec.eligibility."""

    id: str
    condition: str = ""


@dataclass
class AgentSpec:
    id: str
    name: str
    description: str
    system_prompt: str = ""
    # Level 1 (deterministic gate): a boolean expression over session state,
    # e.g. "authenticated == true and region != 'embargoed'". Evaluated by
    # routing/gate.py's safe evaluator — never Python eval(). Empty = always eligible.
    eligibility: str = ""
    # Level 2 (lightweight classifier): keywords/phrases that make this agent a
    # strong candidate for the current utterance. Matched case-insensitively.
    triggers: list[str] = field(default_factory=list)
    # Tools this agent may call, each with its own optional condition.
    tools: list[ToolBinding] = field(default_factory=list)
    # Markdown knowledge files (relative to data/knowledge/) this agent can search
    # via the knowledge_lookup tool, if it has that tool.
    knowledge: list[str] = field(default_factory=list)
    # What this agent says before it has heard anything from the caller.
    # "" = stay silent until the caller speaks first. Normally only the
    # root/receptionist needs one — an agent reached via handoff usually
    # just replies to whatever triggered the handoff. Wired in by
    # voice/worker.py's entrypoint() (session.say()) and cli.py's chat().
    first_message: str = ""
    # Per-agent LLM override (blocco 2, roadmap). "" on provider/model means
    # "inherit the call's own default provider" (config.PROVIDER, chosen
    # once per call) — see llm.py's get_provider_for_agent(). None on
    # temperature means "let the provider use its own default". Only
    # respond() honors llm_temperature; classify() stays on the call's
    # default provider on purpose (routing should stay cheap/deterministic,
    # not vary per destination agent), and so does summarize() (it
    # condenses the whole call, not one agent's turn).
    llm_provider: str = ""
    llm_model: str = ""
    llm_temperature: float | None = None
    # Per-agent ElevenLabs voice override (blocco 2, fixes D1: a `voice`
    # field existed before but nothing ever read it). "" means "inherit
    # whatever TTS voice/worker.py's AgentSession was built with" — see
    # voice/agent.py's OrchestratorAgent.tts_node().
    voice_id: str = ""
    voice_stability: float | None = None
    voice_speed: float | None = None
    children: list["AgentSpec"] = field(default_factory=list)

    def iter_subtree(self):
        """Yields this agent and every descendant, depth-first."""
        yield self
        for child in self.children:
            yield from child.iter_subtree()

    def find(self, agent_id: str) -> "AgentSpec | None":
        for agent in self.iter_subtree():
            if agent.id == agent_id:
                return agent
        return None


def _parse_tool_binding(entry) -> ToolBinding:
    """A tool entry is either a bare id ("knowledge_lookup") or, when it
    needs a condition, a one-key mapping ({id: knowledge_lookup, condition:
    "channel == 'voice'"}). Both are valid YAML; the bare form is just the
    dict form with condition defaulted to "", so existing configs keep working
    unchanged."""
    if isinstance(entry, str):
        return ToolBinding(id=entry)
    return ToolBinding(id=entry["id"], condition=entry.get("condition", ""))


def _parse_node(node: dict) -> AgentSpec:
    children = [_parse_node(c) for c in node.get("children", [])]
    return AgentSpec(
        id=node["id"],
        name=node.get("name", node["id"]),
        description=node.get("description", ""),
        system_prompt=node.get("system_prompt", ""),
        eligibility=node.get("eligibility", ""),
        triggers=list(node.get("triggers", [])),
        tools=[_parse_tool_binding(t) for t in node.get("tools", [])],
        knowledge=list(node.get("knowledge", [])),
        first_message=node.get("first_message", ""),
        llm_provider=node.get("llm_provider", ""),
        llm_model=node.get("llm_model", ""),
        llm_temperature=node.get("llm_temperature"),
        voice_id=node.get("voice_id", ""),
        voice_stability=node.get("voice_stability"),
        voice_speed=node.get("voice_speed"),
        children=children,
    )


def load_family(path: Path) -> AgentSpec:
    """Loads the whole agent family tree from a YAML file. The file's root is
    the router/receptionist agent; everyone else hangs off it as `children`."""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return _parse_node(data["root"])


def _node_to_dict(agent: AgentSpec) -> dict:
    node = {
        "id": agent.id,
        "name": agent.name,
        "description": agent.description,
        "system_prompt": agent.system_prompt,
    }
    if agent.eligibility:
        node["eligibility"] = agent.eligibility
    if agent.triggers:
        node["triggers"] = agent.triggers
    if agent.tools:
        node["tools"] = [
            binding.id if not binding.condition else {"id": binding.id, "condition": binding.condition}
            for binding in agent.tools
        ]
    if agent.knowledge:
        node["knowledge"] = agent.knowledge
    if agent.first_message:
        node["first_message"] = agent.first_message
    if agent.llm_provider:
        node["llm_provider"] = agent.llm_provider
    if agent.llm_model:
        node["llm_model"] = agent.llm_model
    if agent.llm_temperature is not None:
        node["llm_temperature"] = agent.llm_temperature
    if agent.voice_id:
        node["voice_id"] = agent.voice_id
    if agent.voice_stability is not None:
        node["voice_stability"] = agent.voice_stability
    if agent.voice_speed is not None:
        node["voice_speed"] = agent.voice_speed
    if agent.children:
        node["children"] = [_node_to_dict(c) for c in agent.children]
    return node


def save_family(root: AgentSpec, path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump({"root": _node_to_dict(root)}, f, sort_keys=False, allow_unicode=True)


def add_agent(root: AgentSpec, parent_id: str, new_agent: AgentSpec) -> None:
    parent = root.find(parent_id)
    if parent is None:
        raise ValueError(f"No agent with id={parent_id!r} to attach the new agent to")
    if root.find(new_agent.id) is not None:
        raise ValueError(f"Agent id={new_agent.id!r} already exists")
    parent.children.append(new_agent)


def remove_agent(root: AgentSpec, agent_id: str) -> AgentSpec:
    if root.id == agent_id:
        raise ValueError("Cannot remove the root (router) agent")
    for agent in root.iter_subtree():
        for child in list(agent.children):
            if child.id == agent_id:
                agent.children.remove(child)
                return child
    raise ValueError(f"No agent with id={agent_id!r}")
