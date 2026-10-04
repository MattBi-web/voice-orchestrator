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
in `db.py` is the whole "migration" story for now. Fine for a single-table
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
    voice: Mapped[str] = mapped_column(default="default")
    # Position among siblings, so the tree the UI shows has a stable,
    # editor-controlled order instead of whatever SQLite happens to return.
    position: Mapped[int] = mapped_column(default=0)
    triggers_json: Mapped[str] = mapped_column(Text, default="[]")
    tools_json: Mapped[str] = mapped_column(Text, default="[]")
    knowledge_json: Mapped[str] = mapped_column(Text, default="[]")

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
