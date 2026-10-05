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
from ..project import DEFAULT_PROJECT
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
    tts_provider: str = ""
    tts_model: str = ""
    stt_provider: str = ""
    stt_model: str = ""
    stt_language: str = ""


OVERRIDE_FIELDS = ("tts_provider", "tts_model", "stt_provider", "stt_model", "stt_language")


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
        tts_provider=row.tts_provider,
        tts_model=row.tts_model,
        stt_provider=row.stt_provider,
        stt_model=row.stt_model,
        stt_language=row.stt_language,
        children=[],
    )


def project_rows(session: Session, project_id: str) -> list[AgentRow]:
    return list(
        session.scalars(select(AgentRow).where(AgentRow.project_id == project_id).order_by(AgentRow.position)).all()
    )


def build_tree(session: Session, project_id: str = DEFAULT_PROJECT) -> AgentSpec | None:
    """None if the project has no agents (or doesn't exist) — app.py turns
    that into a 4xx rather than a confusing empty tree."""
    rows = project_rows(session, project_id)
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


def get_row(session: Session, agent_id: str, project_id: str = DEFAULT_PROJECT) -> AgentRow:
    row = session.get(AgentRow, (project_id, agent_id))
    if row is None:
        raise AgentNotFound(agent_id)
    return row


def list_tool_ids_in_use(session: Session) -> set[str]:
    rows = session.scalars(select(AgentRow)).all()
    return {t["id"] for row in rows for t in row.tools}


def create_agent(session: Session, data: AgentInput, project_id: str = DEFAULT_PROJECT) -> AgentRow:
    if session.get(AgentRow, (project_id, data.id)) is not None:
        raise AgentIdTaken(data.id)

    has_any = session.scalar(select(AgentRow.id).where(AgentRow.project_id == project_id).limit(1)) is not None
    if data.parent_id is None and has_any:
        raise ParentNotFound("parent_id is required once a root agent already exists")
    if data.parent_id is not None and session.get(AgentRow, (project_id, data.parent_id)) is None:
        raise ParentNotFound(f"No agent with id={data.parent_id!r} to attach the new agent to")

    siblings = session.scalars(
        select(AgentRow).where(AgentRow.project_id == project_id, AgentRow.parent_id == data.parent_id)
    ).all()
    row = AgentRow(
        project_id=project_id,
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
        **{k: getattr(data, k) for k in OVERRIDE_FIELDS},
    )
    row.triggers = data.triggers or []
    row.tools = data.tools or []
    row.knowledge = data.knowledge or []
    session.add(row)
    session.flush()
    return row


def update_agent(session: Session, agent_id: str, data: AgentInput, project_id: str = DEFAULT_PROJECT) -> AgentRow:
    row = get_row(session, agent_id, project_id)
    for key in OVERRIDE_FIELDS:
        setattr(row, key, getattr(data, key))
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


def update_layout(session: Session, agent_id: str, x: float, y: float, project_id: str = DEFAULT_PROJECT) -> AgentRow:
    """Blocco 4: persists where the graph view's drag-and-drop left a node.
    Deliberately its own tiny write, separate from update_agent's full-form
    save — dragging a node shouldn't require (or risk clobbering) the rest
    of that agent's fields."""
    row = get_row(session, agent_id, project_id)
    row.layout_x = x
    row.layout_y = y
    session.flush()
    return row


def _is_descendant(session: Session, ancestor_id: str, candidate_id: str, project_id: str) -> bool:
    """True if candidate_id is ancestor_id itself, or anywhere below it in
    the tree — walked via parent_id rather than loading the whole tree,
    since a family can be reparented one hop at a time without ever
    materializing AgentSpec for this check."""
    if candidate_id == ancestor_id:
        return True
    row = session.get(AgentRow, (project_id, candidate_id))
    while row is not None and row.parent_id is not None:
        if row.parent_id == ancestor_id:
            return True
        row = session.get(AgentRow, (project_id, row.parent_id))
    return False


def reparent_agent(session: Session, agent_id: str, new_parent_id: str, project_id: str = DEFAULT_PROJECT) -> AgentRow:
    """D13 (blocco 4 follow-up): moves an agent (and its whole subtree,
    untouched) under a different parent — what the graph view's
    drag-a-node-onto-another-node does. Its own small write, same shape as
    update_layout: a structural move shouldn't require resending the rest
    of the agent's form, and shouldn't risk clobbering it either."""
    row = get_row(session, agent_id, project_id)
    if row.parent_id is None:
        raise CannotReparentRoot(agent_id)
    new_parent = session.get(AgentRow, (project_id, new_parent_id))
    if new_parent is None:
        raise ParentNotFound(f"No agent with id={new_parent_id!r} to attach to")
    # Moving a node under itself, or under one of its own descendants,
    # would disconnect part of the tree from the root entirely — walk down
    # from the agent being moved (not up from the target) to catch both.
    if _is_descendant(session, ancestor_id=agent_id, candidate_id=new_parent_id, project_id=project_id):
        raise WouldCreateCycle(f"{new_parent_id!r} is {agent_id!r} itself or one of its own descendants")
    if row.parent_id == new_parent_id:
        return row  # already there — a no-op, not an error
    siblings = session.scalars(
        select(AgentRow).where(AgentRow.project_id == project_id, AgentRow.parent_id == new_parent_id)
    ).all()
    row.parent_id = new_parent_id
    row.position = len(siblings)
    session.flush()
    return row


def delete_agent(session: Session, agent_id: str, project_id: str = DEFAULT_PROJECT) -> None:
    row = get_row(session, agent_id, project_id)
    if row.parent_id is None:
        raise CannotDeleteRoot(agent_id)
    has_children = session.scalar(
        select(AgentRow.id).where(AgentRow.project_id == project_id, AgentRow.parent_id == agent_id).limit(1)
    )
    if has_children is not None:
        raise HasChildren(agent_id)
    session.delete(row)
    session.flush()


def insert_subtree(session: Session, project_id: str, node: AgentSpec, parent_id: str | None = None, position: int = 0) -> None:
    """A whole AgentSpec tree into a project (seed, templates, YAML import)."""
    row = AgentRow(
        project_id=project_id,
        id=node.id,
        parent_id=parent_id,
        name=node.name,
        description=node.description,
        system_prompt=node.system_prompt,
        eligibility=node.eligibility,
        first_message=node.first_message,
        llm_provider=node.llm_provider,
        llm_model=node.llm_model,
        llm_temperature=node.llm_temperature,
        voice_id=node.voice_id,
        voice_stability=node.voice_stability,
        voice_speed=node.voice_speed,
        position=position,
        **{k: getattr(node, k) for k in OVERRIDE_FIELDS},
    )
    row.triggers = node.triggers
    row.tools = [{"id": t.id, "condition": t.condition} for t in node.tools]
    row.knowledge = node.knowledge
    session.add(row)
    for i, child in enumerate(node.children):
        insert_subtree(session, project_id, child, parent_id=node.id, position=i)
