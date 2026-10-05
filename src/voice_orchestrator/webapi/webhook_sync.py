"""Mutates `tools.REGISTRY` in place so webhook tools added, edited, or
removed through the web UI become callable on the very next turn — no
process restart needed. Mirrors `mcp_sync.py` exactly, including the
"webapi-only module, orchestrator.py stays untouched" reasoning in its
module docstring: this only ever touches entries whose id starts with
"webhook:", so it can safely drop stale ones without risking any other tool.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..tools import REGISTRY
from ..tools.webhook_tool import WebhookTool
from . import webhook_repository


def sync_registry_from_db(session: Session) -> None:
    rows = webhook_repository.list_tools(session)
    current_ids = {f"webhook:{row.name}" for row in rows}
    for stale_id in [tool_id for tool_id in REGISTRY if tool_id.startswith("webhook:") and tool_id not in current_ids]:
        del REGISTRY[stale_id]
    for row in rows:
        REGISTRY[f"webhook:{row.name}"] = WebhookTool(webhook_repository.row_to_config(row))
