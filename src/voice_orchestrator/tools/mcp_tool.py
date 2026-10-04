"""MCP (Model Context Protocol) tool support — the adapted version of
Rapida's internal/tool/internal/mcp client. An agent points at an MCP server
(here: a local stdio process) and every tool that server exposes becomes
callable, auto-discovered — config, not code, same as the rest of this
project. Configured declaratively in config/mcp_servers.yaml; an absent file
means no MCP tools are registered, not an error.

Kept honest about its limits, same as everywhere else in this project:
`should_trigger`/`run` are synchronous, like every other Tool here, so each
call opens a fresh stdio connection, discovers (or reuses a cached discovery
of) the server's tools, scores them against the utterance with the same
word-overlap heuristic FakeProvider.classify() uses, and calls the best
match with a best-effort single-argument guess. A production integration
would keep one MCP session open for the life of the call instead of
reconnecting every turn, and would let the conversational LLM fill the
tool's arguments via native function-calling (see Rapida's transition_tools
approach) rather than guessing one string into the first parameter.
"""
from __future__ import annotations

import asyncio
import re
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from .. import config
from ..agents.registry import AgentSpec
from ..state import CallSession
from .base import Tool, ToolResult

# Mirrors llm.py's FakeProvider stopword list — kept as its own small copy
# rather than importing llm.py, so this tool has no dependency on the LLM
# provider abstraction at all.
_STOPWORDS = {
    "un", "una", "il", "la", "lo", "gli", "le", "di", "a", "da", "in", "con",
    "su", "per", "tra", "fra", "e", "o", "che", "non", "si", "è", "del", "della",
}


@dataclass(frozen=True)
class MCPServerConfig:
    """How to reach one MCP server over stdio. `name` is just a label used
    in the tool id (mcp:<name>) and in config/mcp_servers.yaml."""

    name: str
    command: str
    args: tuple[str, ...] = ()


@dataclass(frozen=True)
class _RemoteToolInfo:
    name: str
    description: str
    input_properties: tuple[str, ...]


def _word_overlap(utterance: str, haystack: str) -> int:
    words = set(re.findall(r"\w+", utterance.lower())) - _STOPWORDS
    haystack_words = set(re.findall(r"\w+", haystack.lower()))
    return len(words & haystack_words)


async def _discover(server: MCPServerConfig) -> list[_RemoteToolInfo]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=server.command, args=list(server.args))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            return [
                _RemoteToolInfo(
                    name=t.name,
                    description=t.description or "",
                    input_properties=tuple((t.inputSchema or {}).get("properties", {}).keys()),
                )
                for t in listed.tools
            ]


async def _call(server: MCPServerConfig, tool_name: str, arguments: dict) -> str:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=server.command, args=list(server.args))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            parts = [block.text for block in result.content if getattr(block, "text", None)]
            return "\n".join(parts) if parts else str(result.content)


@lru_cache(maxsize=None)
def _discover_cached(server: MCPServerConfig) -> tuple[_RemoteToolInfo, ...]:
    """Discovery is cheap to cache (it's just metadata — name/description/
    input shape) even though we deliberately don't cache the connection
    itself. A failed/unreachable server caches as "no tools" rather than
    retrying every single turn."""
    try:
        return tuple(asyncio.run(_discover(server)))
    except Exception:
        return ()


class MCPTool(Tool):
    """One Tool instance per configured MCP server; `id` is "mcp:<name>" so
    an agent references it in agents.yaml's tools: list like any other id."""

    def __init__(self, server: MCPServerConfig):
        self._server = server
        self.id = f"mcp:{server.name}"
        self.description = f"Tools discovered from the '{server.name}' MCP server."
        self._last_match: str | None = None

    def should_trigger(self, agent: AgentSpec, utterance: str, session: CallSession) -> bool:
        remote_tools = _discover_cached(self._server)
        if not remote_tools:
            self._last_match = None
            return False
        best = max(remote_tools, key=lambda t: _word_overlap(utterance, f"{t.name} {t.description}"))
        if _word_overlap(utterance, f"{best.name} {best.description}") == 0:
            self._last_match = None
            return False
        self._last_match = best.name
        return True

    def run(self, agent: AgentSpec, utterance: str, session: CallSession) -> ToolResult:
        remote_tools = _discover_cached(self._server)
        by_name = {t.name: t for t in remote_tools}
        tool_name = self._last_match or (remote_tools[0].name if remote_tools else None)
        if tool_name is None:
            return ToolResult(summary=f"MCP server '{self._server.name}' exposed no tools (or is unreachable).")

        info = by_name.get(tool_name)
        # Best-effort single-argument guess — see module docstring.
        arguments = {info.input_properties[0]: utterance} if info and info.input_properties else {}

        try:
            summary = asyncio.run(_call(self._server, tool_name, arguments))
        except Exception as exc:
            summary = f"MCP tool '{tool_name}' on '{self._server.name}' failed: {exc}"
        return ToolResult(
            summary=f"[mcp:{self._server.name}/{tool_name}] {summary}",
            data={"tool_name": tool_name, "arguments": arguments},
        )


def load_mcp_tools(path: Path = config.MCP_SERVERS_FILE) -> list[MCPTool]:
    """Reads config/mcp_servers.yaml and returns one MCPTool per entry.
    No file, empty file, or a parse error all mean "no MCP tools" — this is
    an optional feature, and its absence shouldn't break CLI startup."""
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        servers = data.get("servers", [])
        tools = []
        for s in servers:
            command = s["command"]
            # "python"/"python3" means "the interpreter running this
            # process" — spawning a bare `python3` from PATH would miss
            # whatever virtualenv voice-orchestrator itself is installed
            # into (bit us in exactly this way once: worked where the
            # package was installed globally, silently found nothing where
            # it wasn't). A real external server would give its own
            # absolute path or command here instead.
            if command in ("python", "python3"):
                command = sys.executable
            tools.append(MCPTool(MCPServerConfig(name=s["name"], command=command, args=tuple(s.get("args", [])))))
        return tools
    except Exception:
        return []
