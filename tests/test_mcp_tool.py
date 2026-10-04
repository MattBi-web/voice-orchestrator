"""Real (not mocked) integration test against the bundled demo MCP server —
spawns it as an actual stdio subprocess, same code path a user's own MCP
server would go through. No network, no API key: the server is a local
Python process with two toy tools over fake data (demo_mcp_server.py)."""
from __future__ import annotations

import sys

from voice_orchestrator.agents.registry import load_family
from voice_orchestrator.orchestrator import handle_turn
from voice_orchestrator.llm import FakeProvider
from voice_orchestrator.state import CallSession
from voice_orchestrator.tools.mcp_tool import MCPServerConfig, MCPTool
from voice_orchestrator import config


def _demo_server() -> MCPServerConfig:
    # sys.executable, not a bare "python3" — must be the interpreter this
    # test itself is running under (the one with voice_orchestrator
    # installed), same reasoning as load_mcp_tools()'s substitution.
    return MCPServerConfig(name="demo", command=sys.executable, args=("-m", "voice_orchestrator.tools.demo_mcp_server"))


def test_mcp_tool_discovers_and_calls_real_server():
    tool = MCPTool(_demo_server())
    assert tool.id == "mcp:demo"

    triggered = tool.should_trigger(agent=None, utterance="quanto costa il roaming in Francia?", session=CallSession(call_id="t"))
    assert triggered is True

    result = tool.run(agent=None, utterance="quanto costa il roaming in Francia?", session=CallSession(call_id="t"))
    assert "francia" in result.summary.lower() or "France" in result.summary
    assert "€" in result.summary


def test_mcp_tool_does_not_trigger_on_unrelated_utterance():
    tool = MCPTool(_demo_server())
    triggered = tool.should_trigger(agent=None, utterance="buongiorno", session=CallSession(call_id="t"))
    assert triggered is False


def test_roaming_agent_wired_end_to_end():
    """config/agents.yaml's 'roaming' agent uses tools: ["mcp:demo"] — this
    checks the whole path: routing picks the agent, the MCP tool fires, and
    its real response text ends up in tool_ids_used/the reply grounding."""
    root = load_family(config.AGENTS_FILE)
    session = CallSession(call_id="test-mcp-e2e")
    result = handle_turn(session, root, "quanto costa il roaming dati in Francia?", FakeProvider())
    assert result.agent.id == "roaming"
    assert "mcp:demo" in result.tool_ids_used
