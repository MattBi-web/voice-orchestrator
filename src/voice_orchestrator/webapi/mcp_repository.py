"""CRUD over `models.McpServerRow`, and the conversion to
`tools.mcp_tool.MCPServerConfig` — so `mcp_sync.py` can turn whatever's
currently in this table into real, callable `MCPTool` entries in
`tools.REGISTRY`. Mirrors `repository.py`'s shape for the agent table,
including the "flat input dataclass + typed exceptions" style.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..tools.mcp_tool import MCPServerConfig, resolve_command
from .models import McpServerRow


class McpServerNotFound(ValueError):
    pass


class McpServerNameTaken(ValueError):
    pass


@dataclass
class McpServerInput:
    name: str
    command: str
    args: list[str] | None = None


def row_to_config(row: McpServerRow) -> MCPServerConfig:
    """resolve_command() applied here, not at seed/write time — a row keeps
    showing the literal command a person typed or the YAML had ("python3"),
    and only gets resolved to sys.executable the moment it's turned into a
    real, spawnable MCPServerConfig for the registry."""
    return MCPServerConfig(name=row.name, command=resolve_command(row.command), args=tuple(row.args))


def list_servers(session: Session) -> list[McpServerRow]:
    return list(session.scalars(select(McpServerRow).order_by(McpServerRow.name)).all())


def get_row(session: Session, name: str) -> McpServerRow:
    row = session.get(McpServerRow, name)
    if row is None:
        raise McpServerNotFound(name)
    return row


def create_server(session: Session, data: McpServerInput) -> McpServerRow:
    if session.get(McpServerRow, data.name) is not None:
        raise McpServerNameTaken(data.name)
    row = McpServerRow(name=data.name, command=data.command)
    row.args = data.args or []
    session.add(row)
    session.flush()
    return row


def update_server(session: Session, name: str, data: McpServerInput) -> McpServerRow:
    row = get_row(session, name)
    row.command = data.command
    row.args = data.args or []
    session.flush()
    return row


def delete_server(session: Session, name: str) -> None:
    row = get_row(session, name)
    session.delete(row)
    session.flush()
