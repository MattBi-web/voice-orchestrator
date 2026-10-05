"""Shared-mode storage (blocco 6): the database side of what the core keeps
in files by default — finished calls (`call_log.py`), webhook executions
(`tools/webhook_log.py`), the daily voice-minutes tally
(`voice/usage_guard.py`) and knowledge document text (`knowledge.py`).

The core modules call into this only when `config.shared_mode()` is on,
importing it lazily, so the CLI and the test suite keep working with no
sqlalchemy installed. Everything here takes and returns plain dicts and
strings: the dataclasses stay in the core modules that own them.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from . import db
from .models import CallRow, KnowledgeDocRow, UsageDayRow, WebhookExecutionRow


# ---- calls ----


def calls_append(record: dict[str, Any]) -> None:
    with db.session_scope() as s:
        row = s.get(CallRow, record["call_id"]) or CallRow(call_id=record["call_id"])
        row.source = record.get("source", "")
        row.started_at = record.get("started_at", "")
        row.record_json = json.dumps(record)
        s.add(row)


def calls_all() -> list[dict[str, Any]]:
    """Oldest first, like reading the JSONL file top to bottom."""
    with db.session_scope() as s:
        rows = s.scalars(select(CallRow).order_by(CallRow.started_at, CallRow.call_id)).all()
        return [json.loads(r.record_json) for r in rows]


def calls_find(call_id: str) -> dict[str, Any] | None:
    with db.session_scope() as s:
        row = s.get(CallRow, call_id)
        return json.loads(row.record_json) if row else None


# ---- webhook executions ----


def webhook_append(execution: dict[str, Any]) -> None:
    with db.session_scope() as s:
        s.add(WebhookExecutionRow(at=execution.get("at", ""), record_json=json.dumps(execution)))


def webhook_all() -> list[dict[str, Any]]:
    with db.session_scope() as s:
        rows = s.scalars(select(WebhookExecutionRow).order_by(WebhookExecutionRow.id)).all()
        return [json.loads(r.record_json) for r in rows]


# ---- voice minutes ----


def usage_minutes(date: str) -> float:
    with db.session_scope() as s:
        row = s.get(UsageDayRow, date)
        return float(row.minutes) if row else 0.0


def usage_add(date: str, minutes: float) -> None:
    """Row-locked read-modify-write (FOR UPDATE on Postgres; SQLite ignores
    it and serializes writers anyway), so two calls ending together on two
    worker processes both get counted."""
    with db.session_scope() as s:
        row = s.execute(select(UsageDayRow).where(UsageDayRow.date == date).with_for_update()).scalar_one_or_none()
        if row is None:
            s.add(UsageDayRow(date=date, minutes=minutes))
        else:
            row.minutes = float(row.minutes) + minutes


# ---- knowledge text ----


def knowledge_texts(names: list[str] | tuple[str, ...]) -> dict[str, str]:
    """name -> text for the documents that exist, in no particular order
    (callers iterate their own `names` to keep the agent's order)."""
    if not names:
        return {}
    with db.session_scope() as s:
        rows = s.scalars(select(KnowledgeDocRow).where(KnowledgeDocRow.name.in_(list(names)))).all()
        return {r.name: r.content for r in rows if r.content}


def knowledge_fingerprint(names: list[str] | tuple[str, ...]) -> tuple[tuple[str, str, int], ...]:
    """(name, updated_at, length) per requested name — the shared-mode twin
    of knowledge._fingerprint()'s (name, mtime, size): any save changes it,
    so the BM25 index is rebuilt on the next query, on whichever machine."""
    if not names:
        return ()
    with db.session_scope() as s:
        rows = {
            r.name: r
            for r in s.scalars(select(KnowledgeDocRow).where(KnowledgeDocRow.name.in_(list(names)))).all()
        }
    out = []
    for name in names:
        r = rows.get(name)
        out.append((name, r.updated_at, len(r.content)) if r and r.content else (name, "", 0))
    return tuple(out)
