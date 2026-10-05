"""Mutates `tools.REGISTRY` in place so MCP servers added, edited, or
removed through the web UI become callable on the very next turn — no
process restart needed.

This is deliberately a webapi-only module: `orchestrator.py` and
`tools/__init__.py` stay exactly as tested, with no pluggable-registry
parameter added just to serve a newer UI layer (`orchestrator.handle_turn()`
calls `tools.get_tool()` against that same module-level dict either way —
this just keeps it current). It only ever touches entries whose id starts
with "mcp:", so it can safely drop stale ones without risking the three
built-in tools (`transfer_to_human`, `knowledge_lookup`,
`check_account_status`) or anything else a future tool might register.

SECURITY NOTE: an MCP server's `command`/`args` runs as a real local
subprocess (see tools/mcp_tool.py's module docstring on load_mcp_tools()).
Letting a web client create one is a genuine "run an arbitrary command on
this machine" capability. Locally (no VOICE_ORCH_OWNER_PASSWORD) that's
the developer's own machine; hosted (blocco 6), app.py's owner-only-writes
middleware means only the owner can create or edit one — which then runs
on the web service *and* on the voice worker.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..tools import REGISTRY
from ..tools.mcp_tool import MCPTool
from . import mcp_repository


def sync_registry_from_db(session: Session) -> None:
    rows = mcp_repository.list_servers(session)
    current_ids = {f"mcp:{row.name}" for row in rows}
    for stale_id in [tool_id for tool_id in REGISTRY if tool_id.startswith("mcp:") and tool_id not in current_ids]:
        del REGISTRY[stale_id]
    for row in rows:
        REGISTRY[f"mcp:{row.name}"] = MCPTool(mcp_repository.row_to_config(row))
