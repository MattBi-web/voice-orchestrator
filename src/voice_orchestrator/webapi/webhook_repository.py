"""CRUD over `models.WebhookToolRow`, and the conversion to
`tools.webhook_tool.WebhookToolConfig` — so `webhook_sync.py` can turn
whatever's currently in this table into real, callable `WebhookTool` entries
in `tools.REGISTRY`. Mirrors `mcp_repository.py`'s shape exactly, including
the "flat input dataclass + typed exceptions" style.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..tools.webhook_tool import WebhookParam, WebhookToolConfig
from .models import WebhookToolRow


class WebhookToolNotFound(ValueError):
    pass


class WebhookToolNameTaken(ValueError):
    pass


@dataclass
class WebhookToolInput:
    name: str
    description: str = ""
    url: str = ""
    method: str = "POST"
    headers: dict[str, str] = field(default_factory=dict)
    params: list[dict] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)
    timeout_seconds: float = 5.0


def row_to_config(row: WebhookToolRow) -> WebhookToolConfig:
    return WebhookToolConfig(
        name=row.name,
        description=row.description,
        url=row.url,
        method=row.method,
        headers=dict(row.headers),
        params=[WebhookParam(**p) for p in row.params],
        triggers=tuple(row.triggers),
        timeout_seconds=row.timeout_seconds,
    )


def list_tools(session: Session) -> list[WebhookToolRow]:
    return list(session.scalars(select(WebhookToolRow).order_by(WebhookToolRow.name)).all())


def get_row(session: Session, name: str) -> WebhookToolRow:
    row = session.get(WebhookToolRow, name)
    if row is None:
        raise WebhookToolNotFound(name)
    return row


def _apply(row: WebhookToolRow, data: WebhookToolInput) -> None:
    row.description = data.description
    row.url = data.url
    row.method = (data.method or "POST").upper()
    row.headers = data.headers
    row.params = data.params
    row.triggers = data.triggers
    row.timeout_seconds = data.timeout_seconds


def create_tool(session: Session, data: WebhookToolInput) -> WebhookToolRow:
    if session.get(WebhookToolRow, data.name) is not None:
        raise WebhookToolNameTaken(data.name)
    row = WebhookToolRow(name=data.name)
    _apply(row, data)
    session.add(row)
    session.flush()
    return row


def update_tool(session: Session, name: str, data: WebhookToolInput) -> WebhookToolRow:
    row = get_row(session, name)
    _apply(row, data)
    session.flush()
    return row


def delete_tool(session: Session, name: str) -> None:
    row = get_row(session, name)
    session.delete(row)
    session.flush()
