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


class CannotReparentRoot(ValueError):
    pass


class WouldCreateCycle(ValueError):
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
    triggers: list[str] | None = None
    tools: list[dict] | None = None  # [{"id": ..., "condition": ""}]
    knowledge: list[str] | None = None
    first_message: str = ""
    llm_provider: str = ""
    llm_model: str = ""
    llm_temperature: float | None = None
    voice_id: str = ""
    voice_stability: float | None = None
    voice_speed: float | None = None


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
        first_message=row.first_message,
        llm_provider=row.llm_provider,
        llm_model=row.llm_model,
        llm_temperature=row.llm_temperature,
        voice_id=row.voice_id,
        voice_stability=row.voice_stability,
        voice_speed=row.voice_speed,
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
        first_message=data.first_message,
        llm_provider=data.llm_provider,
        llm_model=data.llm_model,
        llm_temperature=data.llm_temperature,
        voice_id=data.voice_id,
        voice_stability=data.voice_stability,
        voice_speed=data.voice_speed,
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
    row.first_message = data.first_message
    row.llm_provider = data.llm_provider
    row.llm_model = data.llm_model
    row.llm_temperature = data.llm_temperature
    row.voice_id = data.voice_id
    row.voice_stability = data.voice_stability
    row.voice_speed = data.voice_speed
    row.triggers = data.triggers or []
    row.tools = data.tools or []
    row.knowledge = data.knowledge or []
    session.flush()
    return row


def update_layout(session: Session, agent_id: str, x: float, y: float) -> AgentRow:
    """Blocco 4: persists where the graph view's drag-and-drop left a node.
    Deliberately its own tiny write, separate from update_agent's full-form
    save — dragging a node shouldn't require (or risk clobbering) the rest
    of that agent's fields."""
    row = get_row(session, agent_id)
    row.layout_x = x
    row.layout_y = y
    session.flush()
    return row


def _is_descendant(session: Session, ancestor_id: str, candidate_id: str) -> bool:
    """True if candidate_id is ancestor_id itself, or anywhere below it in
    the tree — walked via parent_id rather than loading the whole tree,
    since a family can be reparented one hop at a time without ever
    materializing AgentSpec for this check."""
    if candidate_id == ancestor_id:
        return True
    row = session.get(AgentRow, candidate_id)
    while row is not None and row.parent_id is not None:
        if row.parent_id == ancestor_id:
            return True
        row = session.get(AgentRow, row.parent_id)
    return False


def reparent_agent(session: Session, agent_id: str, new_parent_id: str) -> AgentRow:
    """D13 (blocco 4 follow-up): moves an agent (and its whole subtree,
    untouched) under a different parent — what the graph view's
    drag-a-node-onto-another-node does. Its own small write, same shape as
    update_layout: a structural move shouldn't require resending the rest
    of the agent's form, and shouldn't risk clobbering it either."""
    row = get_row(session, agent_id)
    if row.parent_id is None:
        raise CannotReparentRoot(agent_id)
    new_parent = session.get(AgentRow, new_parent_id)
    if new_parent is None:
        raise ParentNotFound(f"No agent with id={new_parent_id!r} to attach to")
    # Moving a node under itself, or under one of its own descendants,
    # would disconnect part of the tree from the root entirely — walk down
    # from the agent being moved (not up from the target) to catch both.
    if _is_descendant(session, ancestor_id=agent_id, candidate_id=new_parent_id):
        raise WouldCreateCycle(f"{new_parent_id!r} is {agent_id!r} itself or one of its own descendants")
    if row.parent_id == new_parent_id:
        return row  # already there — a no-op, not an error
    siblings = session.scalars(select(AgentRow).where(AgentRow.parent_id == new_parent_id)).all()
    row.parent_id = new_parent_id
    row.position = len(siblings)
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
