"""CRUD + tree-assembly over `models.AgentRow`, and the conversion back to
`agents.registry.AgentSpec`/`ToolBinding` — so `app.py`'s test-route endpoint
can hand a DB-backed family straight to the exact same `routing.router.route`
/ `orchestrator.handle_turn` the CLI and the whole text core already use,
with no special-cased "web" code path through the router itself.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agents.registry import AgentSpec, ToolBinding
from .models import AgentRow


class AgentNotFound(ValueError):
    pass


class AgentIdTaken(ValueError):
    pass


class ParentNotFound(ValueError):
    pass


class HasChildren(ValueError):
    pass


class CannotDeleteRoot(ValueError):
    pass


@dataclass
class AgentInput:
    """What the API accepts from a create/update request — a flat, DB-row
    shape (parent_id separate from the rest) rather than AgentSpec's nested
    `children` field, which this layer never reads or writes directly."""

    id: str
    parent_id: str | None
    name: str
    description: str = ""
    system_prompt: str = ""
    eligibility: str = ""
    voice: str = "default"
    triggers: list[str] | None = None
    tools: list[dict] | None = None  # [{"id": ..., "condition": ""}]
    knowledge: list[str] | None = None


def row_to_spec(row: AgentRow) -> AgentSpec:
    """children is always [] here — only build_tree() fills it in, since a
    single row has no idea who its children are without querying siblings."""
    return AgentSpec(
        id=row.id,
        name=row.name,
        description=row.description,
        system_prompt=row.system_prompt,
        eligibility=row.eligibility,
        triggers=row.triggers,
        tools=[ToolBinding(id=t["id"], condition=t.get("condition", "")) for t in row.tools],
        knowledge=row.knowledge,
        voice=row.voice,
        children=[],
    )


def build_tree(session: Session) -> AgentSpec | None:
    """None if the database is empty (nothing seeded yet) — app.py turns
    that into a 404 rather than a confusing empty tree."""
    rows = session.scalars(select(AgentRow).order_by(AgentRow.position)).all()
    if not rows:
        return None
    specs_by_id = {row.id: row_to_spec(row) for row in rows}
    root: AgentSpec | None = None
    for row in rows:
        spec = specs_by_id[row.id]
        if row.parent_id is None:
            root = spec
        else:
            parent = specs_by_id.get(row.parent_id)
            if parent is not None:  # an orphaned row (shouldn't happen) is just dropped from the tree
                parent.children.append(spec)
    return root


def get_row(session: Session, agent_id: str) -> AgentRow:
    row = session.get(AgentRow, agent_id)
    if row is None:
        raise AgentNotFound(agent_id)
    return row


def list_tool_ids_in_use(session: Session) -> set[str]:
    rows = session.scalars(select(AgentRow)).all()
    return {t["id"] for row in rows for t in row.tools}


def create_agent(session: Session, data: AgentInput) -> AgentRow:
    if session.get(AgentRow, data.id) is not None:
        raise AgentIdTaken(data.id)

    has_any = session.scalar(select(AgentRow.id).limit(1)) is not None
    if data.parent_id is None and has_any:
        raise ParentNotFound("parent_id is required once a root agent already exists")
    if data.parent_id is not None and session.get(AgentRow, data.parent_id) is None:
        raise ParentNotFound(f"No agent with id={data.parent_id!r} to attach the new agent to")

    siblings = session.scalars(select(AgentRow).where(AgentRow.parent_id == data.parent_id)).all()
    row = AgentRow(
        id=data.id,
        parent_id=data.parent_id,
        name=data.name,
        description=data.description,
        system_prompt=data.system_prompt,
        eligibility=data.eligibility,
        voice=data.voice,
        position=len(siblings),
    )
    row.triggers = data.triggers or []
    row.tools = data.tools or []
    row.knowledge = data.knowledge or []
    session.add(row)
    session.flush()
    return row


def update_agent(session: Session, agent_id: str, data: AgentInput) -> AgentRow:
    row = get_row(session, agent_id)
    row.name = data.name
    row.description = data.description
    row.system_prompt = data.system_prompt
    row.eligibility = data.eligibility
    row.voice = data.voice
    row.triggers = data.triggers or []
    row.tools = data.tools or []
    row.knowledge = data.knowledge or []
    session.flush()
    return row


def delete_agent(session: Session, agent_id: str) -> None:
    row = get_row(session, agent_id)
    if row.parent_id is None:
        raise CannotDeleteRoot(agent_id)
    has_children = session.scalar(select(AgentRow.id).where(AgentRow.parent_id == agent_id).limit(1))
    if has_children is not None:
        raise HasChildren(agent_id)
    session.delete(row)
    session.flush()
