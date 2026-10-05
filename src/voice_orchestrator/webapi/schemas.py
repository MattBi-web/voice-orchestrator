"""Pydantic request/response shapes for the agent-builder API. `AgentOut`
mirrors `models.AgentRow` plus a nested `children` list (what the frontend's
tree view actually wants); `AgentIn`/`AgentUpdate` are the flat, DB-row
shape `repository.AgentInput` already expects, so `app.py`'s routes barely
have to touch the data between a request body and a repository call.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .models import AgentRow, McpServerRow, WebhookToolRow


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
    triggers: list[str] = Field(default_factory=list)
    tools: list[ToolBindingSchema] = Field(default_factory=list)
    knowledge: list[str] = Field(default_factory=list)
    first_message: str = ""
    llm_provider: str = ""
    llm_model: str = ""
    llm_temperature: float | None = None
    voice_id: str = ""
    voice_stability: float | None = None
    voice_speed: float | None = None


class AgentUpdate(BaseModel):
    name: str
    description: str = ""
    system_prompt: str = ""
    eligibility: str = ""
    triggers: list[str] = Field(default_factory=list)
    tools: list[ToolBindingSchema] = Field(default_factory=list)
    knowledge: list[str] = Field(default_factory=list)
    first_message: str = ""
    llm_provider: str = ""
    llm_model: str = ""
    llm_temperature: float | None = None
    voice_id: str = ""
    voice_stability: float | None = None
    voice_speed: float | None = None


class AgentLayoutUpdate(BaseModel):
    """Blocco 4 — the graph view's drag-and-drop PATCHes just this, not a
    whole AgentUpdate, so repositioning a node can't accidentally touch
    anything else about it."""

    layout_x: float
    layout_y: float


class AgentReparentRequest(BaseModel):
    """D13 — dropping a node onto another one in the graph PATCHes just
    this: the new parent id. Validated server-side (repository.reparent_agent)
    against moving the root and against creating a cycle."""

    parent_id: str


class AgentOut(BaseModel):
    id: str
    parent_id: str | None
    name: str
    description: str
    system_prompt: str
    eligibility: str
    triggers: list[str]
    tools: list[ToolBindingSchema]
    knowledge: list[str]
    first_message: str
    llm_provider: str
    llm_model: str
    llm_temperature: float | None
    voice_id: str
    voice_stability: float | None
    voice_speed: float | None
    layout_x: float | None = None
    layout_y: float | None = None
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
        triggers=row.triggers,
        tools=[ToolBindingSchema(**t) for t in row.tools],
        knowledge=row.knowledge,
        first_message=row.first_message,
        llm_provider=row.llm_provider,
        llm_model=row.llm_model,
        llm_temperature=row.llm_temperature,
        voice_id=row.voice_id,
        voice_stability=row.voice_stability,
        voice_speed=row.voice_speed,
        layout_x=row.layout_x,
        layout_y=row.layout_y,
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


class WebhookParamSchema(BaseModel):
    name: str
    source: Literal["slot", "literal"] = "slot"
    value: str = ""
    type: Literal["string", "number", "boolean"] = "string"


class WebhookToolIn(BaseModel):
    """`name` is only read on create — PUT's path parameter identifies the
    row being updated, same convention as McpServerIn."""

    name: str
    description: str = ""
    url: str = ""
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "POST"
    headers: dict[str, str] = Field(default_factory=dict)
    params: list[WebhookParamSchema] = Field(default_factory=list)
    triggers: list[str] = Field(default_factory=list)
    timeout_seconds: float = 5.0


class WebhookToolOut(BaseModel):
    name: str
    description: str
    url: str
    method: str
    headers: dict[str, str]
    params: list[WebhookParamSchema]
    triggers: list[str]
    timeout_seconds: float


def webhook_row_to_out(row: WebhookToolRow) -> WebhookToolOut:
    return WebhookToolOut(
        name=row.name,
        description=row.description,
        url=row.url,
        method=row.method,
        headers=row.headers,
        params=[WebhookParamSchema(**p) for p in row.params],
        triggers=row.triggers,
        timeout_seconds=row.timeout_seconds,
    )


class WebhookExecutionOut(BaseModel):
    """Mirrors tools/webhook_log.py's Execution dataclass — one row per
    logged call to a custom HTTP tool."""

    tool_name: str
    call_id: str
    agent_id: str
    url: str
    method: str
    ok: bool
    status_code: int | None
    latency_ms: float
    error: str
    at: str


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
