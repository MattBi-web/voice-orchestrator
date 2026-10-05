"""The SQLite schema for the web-editable agent family — one `agents` table,
self-referential via `parent_id`, with triggers/tools/knowledge stored as
JSON-encoded lists on the row rather than their own child tables.

That's a deliberate simplification, not an oversight: none of those three
lists are ever queried or filtered on their own (no "find every agent using
tool X" feature in this version), they're only ever read or written whole,
together with their parent agent — exactly the shape a form in the frontend
edits and saves in one request. Three extra tables and the joins to match
would buy nothing this version actually uses. If a future version needs to
query across tools or triggers, that's the moment to normalize them out.

No migration framework (Alembic, etc.) either — `Base.metadata.create_all()`
plus `db.sync_columns()` (adds columns a newer model maps) is the whole
"migration" story for now. Fine for a single-table
schema in active development; worth revisiting before this schema needs to
change under real user data someone cares about keeping.
"""
from __future__ import annotations

import json

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AgentRow(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(primary_key=True)
    # NULL only for the root (receptionist/router) agent — mirrors
    # agents/registry.py's AgentSpec tree, where the root is the one node
    # with no parent and everyone else hangs off it via `children`.
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    name: Mapped[str] = mapped_column(default="")
    description: Mapped[str] = mapped_column(default="")
    system_prompt: Mapped[str] = mapped_column(default="")
    eligibility: Mapped[str] = mapped_column(default="")
    # Position among siblings, so the tree the UI shows has a stable,
    # editor-controlled order instead of whatever SQLite happens to return.
    position: Mapped[int] = mapped_column(default=0)
    triggers_json: Mapped[str] = mapped_column(Text, default="[]")
    tools_json: Mapped[str] = mapped_column(Text, default="[]")
    knowledge_json: Mapped[str] = mapped_column(Text, default="[]")
    # Blocco 2 — see agents/registry.py's AgentSpec for what each means;
    # these mirror it column-for-column, same convention as every other
    # field above.
    first_message: Mapped[str] = mapped_column(Text, default="")
    llm_provider: Mapped[str] = mapped_column(default="")
    llm_model: Mapped[str] = mapped_column(default="")
    llm_temperature: Mapped[float | None] = mapped_column(nullable=True, default=None)
    voice_id: Mapped[str] = mapped_column(default="")
    voice_stability: Mapped[float | None] = mapped_column(nullable=True, default=None)
    voice_speed: Mapped[float | None] = mapped_column(nullable=True, default=None)
    # Blocco 4 — where the graph view put this node after a drag. None for
    # both = let the frontend auto-layout it (a fresh/never-dragged agent).
    layout_x: Mapped[float | None] = mapped_column(nullable=True, default=None)
    layout_y: Mapped[float | None] = mapped_column(nullable=True, default=None)

    @property
    def triggers(self) -> list[str]:
        return json.loads(self.triggers_json or "[]")

    @triggers.setter
    def triggers(self, value: list[str]) -> None:
        self.triggers_json = json.dumps(list(value))

    @property
    def tools(self) -> list[dict]:
        """Each item is `{"id": "<tool id>", "condition": "<gate expr or ''>"}`
        — the JSON-friendly shape of agents/registry.py's `ToolBinding`."""
        return json.loads(self.tools_json or "[]")

    @tools.setter
    def tools(self, value: list[dict]) -> None:
        self.tools_json = json.dumps(list(value))

    @property
    def knowledge(self) -> list[str]:
        return json.loads(self.knowledge_json or "[]")

    @knowledge.setter
    def knowledge(self, value: list[str]) -> None:
        self.knowledge_json = json.dumps(list(value))


class McpServerRow(Base):
    """The web-editable mirror of config/mcp_servers.yaml's `servers:` list —
    same dual-source-of-truth pattern as AgentRow/agents.yaml above: seeded
    once from the YAML (webapi/seed.py), then independent of it. `name` is
    the primary key (and the suffix of the tool id "mcp:<name>"), so renaming
    a server means delete + recreate, same as an agent's `id` can't change
    after creation either."""

    __tablename__ = "mcp_servers"

    name: Mapped[str] = mapped_column(primary_key=True)
    command: Mapped[str] = mapped_column(default="")
    args_json: Mapped[str] = mapped_column(Text, default="[]")

    @property
    def args(self) -> list[str]:
        return json.loads(self.args_json or "[]")

    @args.setter
    def args(self, value: list[str]) -> None:
        self.args_json = json.dumps(list(value))


class WebhookToolRow(Base):
    """The web-editable mirror of config/webhook_tools.yaml's `tools:` list —
    same dual-source-of-truth pattern as McpServerRow/mcp_servers.yaml.
    `name` is the primary key (and the suffix of the tool id
    "webhook:<name>"), so renaming a tool means delete + recreate, same
    convention as McpServerRow.

    `headers_json` stores whatever string a person types, including a
    "{{secret:NAME}}" placeholder — never a resolved secret value; see
    tools/webhook_tool.py's module docstring for why that's safe to keep in
    this (unencrypted, browser-editable) table."""

    __tablename__ = "webhook_tools"

    name: Mapped[str] = mapped_column(primary_key=True)
    description: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(default="")
    method: Mapped[str] = mapped_column(default="POST")
    headers_json: Mapped[str] = mapped_column(Text, default="{}")
    params_json: Mapped[str] = mapped_column(Text, default="[]")
    triggers_json: Mapped[str] = mapped_column(Text, default="[]")
    timeout_seconds: Mapped[float] = mapped_column(default=5.0)

    @property
    def headers(self) -> dict[str, str]:
        return json.loads(self.headers_json or "{}")

    @headers.setter
    def headers(self, value: dict[str, str]) -> None:
        self.headers_json = json.dumps(dict(value))

    @property
    def params(self) -> list[dict]:
        """Each item is `{"name", "source", "value", "type"}` — the
        JSON-friendly shape of tools/webhook_tool.py's `WebhookParam`."""
        return json.loads(self.params_json or "[]")

    @params.setter
    def params(self, value: list[dict]) -> None:
        self.params_json = json.dumps(list(value))

    @property
    def triggers(self) -> list[str]:
        return json.loads(self.triggers_json or "[]")

    @triggers.setter
    def triggers(self, value: list[str]) -> None:
        self.triggers_json = json.dumps(list(value))


class AppMetaRow(Base):
    """Tiny key/value table for one-off flags — today only "this seed already
    ran", so emptying a table on purpose (deleting every criterion, say)
    isn't silently undone by the next startup's seed-if-empty check."""

    __tablename__ = "app_meta"

    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[str] = mapped_column(default="")


class EvaluationCriterionRow(Base):
    """One success criterion (analysis.EvaluationCriterion). Family-wide, not
    per agent: a call crosses several agents, and it's the whole call that
    gets judged — see docs/ROADMAP.md's decision log."""

    __tablename__ = "evaluation_criteria"

    id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(default="")
    prompt: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(default=0)
    # D11 — analysis.KIND_* and its argument list (agent or tool ids).
    kind: Mapped[str] = mapped_column(default="llm")
    expected_json: Mapped[str] = mapped_column(Text, default="[]")


class DataCollectionItemRow(Base):
    """One field to extract from every analyzed call (analysis.DataCollectionItem)."""

    __tablename__ = "data_collection_items"

    id: Mapped[str] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(default="string")
    description: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(default=0)


class CallAnalysisRow(Base):
    """The latest analysis of one call. The transcript itself stays in the
    core's call_log.jsonl (keyed by the same call_id); only the web API's own
    judgement of it lives here, since criteria are a web-API concept too."""

    __tablename__ = "call_analyses"

    call_id: Mapped[str] = mapped_column(primary_key=True)
    analyzed_at: Mapped[str] = mapped_column(default="")
    method: Mapped[str] = mapped_column(default="")
    provider: Mapped[str] = mapped_column(default="")
    call_successful: Mapped[str] = mapped_column(default="unknown")
    result_json: Mapped[str] = mapped_column(Text, default="{}")


class KnowledgeDocRow(Base):
    """Where a knowledge document came from (blocco 5). The content itself
    is the file in `config.KNOWLEDGE_DIR` — the only copy, read the same way
    by the CLI, the voice worker and this API (see knowledge.py). A file
    with no row here (the bundled demo files, or one copied in by hand) is
    still a perfectly valid document; it just has no recorded source."""

    __tablename__ = "knowledge_docs"

    name: Mapped[str] = mapped_column(primary_key=True)
    source_type: Mapped[str] = mapped_column(default="")  # "text" | "file" | "url"
    source_url: Mapped[str] = mapped_column(default="")
    updated_at: Mapped[str] = mapped_column(default="")

