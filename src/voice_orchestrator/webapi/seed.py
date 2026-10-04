"""One-time import: config/agents.yaml -> the web API's SQLite database.

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
from .models import AgentRow


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
