"""Pydantic request/response shapes for the agent-builder API. `AgentOut`
mirrors `models.AgentRow` plus a nested `children` list (what the frontend's
tree view actually wants); `AgentIn`/`AgentUpdate` are the flat, DB-row
shape `repository.AgentInput` already expects, so `app.py`'s routes barely
have to touch the data between a request body and a repository call.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .models import AgentRow, McpServerRow


class ToolBindingSchema(BaseModel):
    id: str
    condition: str = ""


class AgentIn(BaseModel):
    id: str
    parent_id: str | None = None
    name: str
    description: str = ""
    system_prompt: str = ""
    eligibility: str = ""
    voice: str = "default"
    triggers: list[str] = Field(default_factory=list)
    tools: list[ToolBindingSchema] = Field(default_factory=list)
    knowledge: list[str] = Field(default_factory=list)


class AgentUpdate(BaseModel):
    name: str
    description: str = ""
    system_prompt: str = ""
    eligibility: str = ""
    voice: str = "default"
    triggers: list[str] = Field(default_factory=list)
    tools: list[ToolBindingSchema] = Field(default_factory=list)
    knowledge: list[str] = Field(default_factory=list)


class AgentOut(BaseModel):
    id: str
    parent_id: str | None
    name: str
    description: str
    system_prompt: str
    eligibility: str
    voice: str
    triggers: list[str]
    tools: list[ToolBindingSchema]
    knowledge: list[str]
    children: list["AgentOut"] = Field(default_factory=list)
    children_ids: list[str] = Field(default_factory=list)


AgentOut.model_rebuild()


def row_to_out(row: AgentRow, children: list[AgentOut] | None = None) -> AgentOut:
    children = children or []
    return AgentOut(
        id=row.id,
        parent_id=row.parent_id,
        name=row.name,
        description=row.description,
        system_prompt=row.system_prompt,
        eligibility=row.eligibility,
        voice=row.voice,
        triggers=row.triggers,
        tools=[ToolBindingSchema(**t) for t in row.tools],
        knowledge=row.knowledge,
        children=children,
        children_ids=[c.id for c in children],
    )


def build_agent_out_tree(rows: list[AgentRow]) -> AgentOut | None:
    outs_by_id = {row.id: row_to_out(row) for row in rows}
    root: AgentOut | None = None
    for row in rows:
        out = outs_by_id[row.id]
        if row.parent_id is None:
            root = out
        else:
            parent = outs_by_id.get(row.parent_id)
            if parent is not None:
                parent.children.append(out)
    return root


class TestRouteRequest(BaseModel):
    utterance: str
    start_agent_id: str | None = None  # defaults to the family's root
    channel: str = "voice"
    slots: dict = Field(default_factory=dict)


class TestRouteResponse(BaseModel):
    agent_id: str
    agent_name: str
    resolved_by: str
    eligible_agents: list[str]
    handed_off: bool
    reply: str
    tool_ids_used: list[str]


class McpServerIn(BaseModel):
    """`name` is only read on create — PUT's path parameter is what
    identifies the row being updated, same as AgentUpdate's id."""

    name: str
    command: str
    args: list[str] = Field(default_factory=list)


class McpServerOut(BaseModel):
    name: str
    command: str
    args: list[str]


def mcp_row_to_out(row: McpServerRow) -> McpServerOut:
    return McpServerOut(name=row.name, command=row.command, args=row.args)


class CriterionSchema(BaseModel):
    id: str
    name: str = ""
    prompt: str


class DataItemSchema(BaseModel):
    id: str
    type: Literal["string", "boolean", "integer", "number"] = "string"
    description: str


class AnalysisConfigSchema(BaseModel):
    """The whole family-wide analysis config — read and saved as one unit,
    the way the settings form edits it."""

    criteria: list[CriterionSchema] = Field(default_factory=list)
    data_items: list[DataItemSchema] = Field(default_factory=list)
