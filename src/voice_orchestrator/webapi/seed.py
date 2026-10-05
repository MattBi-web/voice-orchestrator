"""One-time import: config/agents.yaml -> the web API's SQLite database, and
likewise config/mcp_servers.yaml -> its own mirror table.

Runs automatically on API startup (see app.py's lifespan) only when the
database is still empty — so it seeds the Meridian Telecom demo family the
very first time, and never again overwrites whatever a user has since
edited through the browser. `reseed()` is the explicit, destructive version
for development (wipe the DB and re-import from YAML), never called
automatically.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..agents.registry import load_family_file
from ..project import DEFAULT_PROJECT, ModelSettings
from ..analysis import DEFAULT_CRITERIA, DEFAULT_DATA_ITEMS
from ..tools.mcp_tool import read_raw_server_entries
from ..tools.webhook_tool import read_raw_entries as read_raw_webhook_entries
from . import analysis_repository, repository
from .models import AgentRow, AppMetaRow, ProjectRow, DataCollectionItemRow, EvaluationCriterionRow, McpServerRow, WebhookToolRow


def _already_seeded(session: Session, key: str) -> bool:
    return session.get(AppMetaRow, key) is not None


def _mark_seeded(session: Session, key: str) -> None:
    if session.get(AppMetaRow, key) is None:
        session.add(AppMetaRow(key=key, value="1"))


def _create_demo(session: Session, yaml_path: Path | None) -> None:
    from . import project_repository

    path = yaml_path or config.AGENTS_FILE
    root, meta = load_family_file(path)
    row = ProjectRow(
        id=DEFAULT_PROJECT,
        name=meta.get("name", "Demo"),
        description=meta.get("description", ""),
        created_at=project_repository._now(),
        updated_at=project_repository._now(),
        position=0,
    )
    row.settings = ModelSettings.from_dict(meta.get("settings")).as_dict()
    session.add(row)
    repository.insert_subtree(session, DEFAULT_PROJECT, root)


def seed_if_empty(session: Session, yaml_path: Path | None = None) -> bool:
    """Returns True if it actually seeded anything, False if projects
    already existed. Blocco 8: the YAML family becomes the "demo" project;
    a database migrated from before projects only gets that project's row
    (its agents are already there)."""
    from . import project_repository

    if session.scalar(select(ProjectRow.id).limit(1)) is not None:
        return False
    if project_repository.ensure_demo(session):
        session.commit()
        return True
    _create_demo(session, yaml_path)
    session.commit()
    return True


def reseed(session: Session, yaml_path: Path | None = None) -> None:
    """Wipes every project and agent and re-imports the demo from YAML —
    destructive, only for development resets. Never called by app.py's
    startup path."""
    session.query(AgentRow).delete()
    session.query(ProjectRow).delete()
    session.commit()
    _create_demo(session, yaml_path)
    session.commit()


def seed_mcp_if_empty(session: Session, yaml_path: Path | None = None) -> bool:
    """Same idempotent "only if empty" import as seed_if_empty, for the MCP
    servers table. Stores each entry's command exactly as YAML wrote it
    (e.g. "python3"), not resolve_command()'s substitution — see
    mcp_repository.row_to_config for where that substitution actually
    happens, applied fresh every time a row becomes a real MCPServerConfig."""
    already_has_rows = session.scalar(select(McpServerRow.name).limit(1)) is not None
    if already_has_rows or _already_seeded(session, "mcp_servers_seeded"):
        # The flag is what keeps "I deleted every server on purpose" from
        # being undone by the next restart; a pre-flag DB that already has
        # rows just gets the flag set now.
        _mark_seeded(session, "mcp_servers_seeded")
        session.commit()
        return False
    for entry in read_raw_server_entries(yaml_path or config.MCP_SERVERS_FILE):
        row = McpServerRow(name=entry["name"], command=entry["command"])
        row.args = list(entry.get("args", []))
        session.add(row)
    _mark_seeded(session, "mcp_servers_seeded")
    session.commit()
    return True


def seed_webhook_tools_if_empty(session: Session, yaml_path: Path | None = None) -> bool:
    """Same idempotent "only if empty" import as seed_mcp_if_empty, for the
    webhook tools table — config/webhook_tools.yaml -> WebhookToolRow."""
    already_has_rows = session.scalar(select(WebhookToolRow.name).limit(1)) is not None
    if already_has_rows or _already_seeded(session, "webhook_tools_seeded"):
        _mark_seeded(session, "webhook_tools_seeded")
        session.commit()
        return False
    for entry in read_raw_webhook_entries(yaml_path or config.WEBHOOK_TOOLS_FILE):
        row = WebhookToolRow(
            name=entry["name"],
            description=entry.get("description", ""),
            url=entry.get("url", ""),
            method=entry.get("method", "POST"),
            timeout_seconds=float(entry.get("timeout_seconds", 5.0)),
        )
        row.headers = dict(entry.get("headers") or {})
        row.params = list(entry.get("params", []))
        row.triggers = list(entry.get("triggers", []))
        session.add(row)
    _mark_seeded(session, "webhook_tools_seeded")
    session.commit()
    return True


def seed_analysis_if_empty(session: Session) -> bool:
    """Default criteria and data-collection fields (analysis.DEFAULT_*), seeded
    once. No YAML twin this time: nothing outside the web API reads these, so
    there's no second source of truth to keep in step."""
    if _already_seeded(session, "analysis_config_seeded"):
        return False
    for i, c in enumerate(DEFAULT_CRITERIA):
        session.add(analysis_repository.criterion_row(c, i))
    for i, d in enumerate(DEFAULT_DATA_ITEMS):
        session.add(DataCollectionItemRow(id=d.id, type=d.type, description=d.description, position=i))
    _mark_seeded(session, "analysis_config_seeded")
    session.commit()
    return True
