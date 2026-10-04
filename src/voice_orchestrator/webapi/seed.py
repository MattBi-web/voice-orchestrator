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
from ..agents.registry import AgentSpec, load_family
from ..analysis import DEFAULT_CRITERIA, DEFAULT_DATA_ITEMS
from ..tools.mcp_tool import read_raw_server_entries
from .models import AgentRow, AppMetaRow, DataCollectionItemRow, EvaluationCriterionRow, McpServerRow


def _already_seeded(session: Session, key: str) -> bool:
    return session.get(AppMetaRow, key) is not None


def _mark_seeded(session: Session, key: str) -> None:
    if session.get(AppMetaRow, key) is None:
        session.add(AppMetaRow(key=key, value="1"))


def _insert_subtree(session: Session, node: AgentSpec, parent_id: str | None, position: int) -> None:
    row = AgentRow(
        id=node.id,
        parent_id=parent_id,
        name=node.name,
        description=node.description,
        system_prompt=node.system_prompt,
        eligibility=node.eligibility,
        voice=node.voice,
        position=position,
    )
    row.triggers = node.triggers
    row.tools = [{"id": t.id, "condition": t.condition} for t in node.tools]
    row.knowledge = node.knowledge
    session.add(row)
    for i, child in enumerate(node.children):
        _insert_subtree(session, child, parent_id=node.id, position=i)


def seed_if_empty(session: Session, yaml_path: Path | None = None) -> bool:
    """Returns True if it actually seeded anything (the DB was empty),
    False if it found existing rows and left them untouched."""
    already_has_rows = session.scalar(select(AgentRow.id).limit(1)) is not None
    if already_has_rows:
        return False
    root = load_family(yaml_path or config.AGENTS_FILE)
    _insert_subtree(session, root, parent_id=None, position=0)
    session.commit()
    return True


def reseed(session: Session, yaml_path: Path | None = None) -> None:
    """Wipes every row and re-imports from YAML — destructive, only for
    development resets. Never called by app.py's startup path."""
    session.query(AgentRow).delete()
    session.commit()
    root = load_family(yaml_path or config.AGENTS_FILE)
    _insert_subtree(session, root, parent_id=None, position=0)
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


def seed_analysis_if_empty(session: Session) -> bool:
    """Default criteria and data-collection fields (analysis.DEFAULT_*), seeded
    once. No YAML twin this time: nothing outside the web API reads these, so
    there's no second source of truth to keep in step."""
    if _already_seeded(session, "analysis_config_seeded"):
        return False
    for i, c in enumerate(DEFAULT_CRITERIA):
        session.add(EvaluationCriterionRow(id=c.id, name=c.name, prompt=c.prompt, position=i))
    for i, d in enumerate(DEFAULT_DATA_ITEMS):
        session.add(DataCollectionItemRow(id=d.id, type=d.type, description=d.description, position=i))
    _mark_seeded(session, "analysis_config_seeded")
    session.commit()
    return True
