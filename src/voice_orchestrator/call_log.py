"""A durable, append-only log of finished calls — one JSON line per call,
written by whichever surface ends a call (`cli.py`'s `chat()` loop, the
voice worker's shutdown callback, the webapi's own `/api/test/route`) and
read back by the agent-builder's analytics dashboard
(`webapi/app.py`'s `GET /api/calls*`).

Deliberately a plain JSONL file, not a SQLite table: this module lives in
the core (`voice_orchestrator/call_log.py`), which `cli.py` and
`voice/worker.py` both import with none of `webapi`'s extra dependencies
(sqlalchemy/fastapi) installed — the same "nothing else imports these"
promise `webapi/__init__.py` documents for the reverse direction. An
append-only file needs nothing beyond the standard library, the same ethos
as `usage_guard.py`'s single-state JSON file — just append-only instead of
overwrite-in-place, since many calls need to coexist rather than one
running tally.

Not a database: filtering/aggregating happens in Python once the file is
read back (`data/call_log.jsonl` is expected to stay small — a portfolio
demo's worth of test calls, not production call volume). If this ever needs
to hold more than a few thousand calls, this is the place to swap for
something with an index, not a reason to distrust the abstraction today.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config
from .observability import COMPONENT_TOOL, EVENT_TOOL_TRIGGERED
from .state import CallSession


@dataclass
class CallRecord:
    call_id: str
    source: str  # "chat" | "voice" | "route_test"
    channel: str
    started_at: str  # ISO 8601, UTC
    ended_at: str
    duration_seconds: float
    turn_count: int
    final_agent_id: str | None
    resolved_by_counts: dict[str, int] = field(default_factory=dict)
    tool_counts: dict[str, int] = field(default_factory=dict)
    handoffs: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _tool_counts(session: CallSession) -> dict[str, int]:
    counts: dict[str, int] = {}
    for evt in session.event_log:
        if evt.component == COMPONENT_TOOL and evt.event == EVENT_TOOL_TRIGGERED:
            tool_id = str(evt.attributes.get("tool_id", "?"))
            counts[tool_id] = counts.get(tool_id, 0) + 1
    return counts


def from_session(
    session: CallSession,
    source: str,
    started_at: datetime,
    ended_at: datetime | None = None,
) -> CallRecord:
    """Builds the record purely from what `CallSession` already tracks —
    `routing_stats()`, `event_log`, `handoff_log` — so this is a summary of
    real call state, not a second bookkeeping system a caller has to feed by
    hand."""
    ended = ended_at or datetime.now(timezone.utc)
    return CallRecord(
        call_id=session.call_id,
        source=source,
        channel=session.channel,
        started_at=started_at.isoformat(),
        ended_at=ended.isoformat(),
        duration_seconds=max((ended - started_at).total_seconds(), 0.0),
        turn_count=len(session.full_log),
        final_agent_id=session.current_agent_id,
        resolved_by_counts=session.routing_stats(),
        tool_counts=_tool_counts(session),
        handoffs=len(session.handoff_log),
    )


def append(record: CallRecord, path: Path | None = None) -> None:
    p = path or config.CALL_LOG_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record.as_dict()) + "\n")


def read_all(path: Path | None = None) -> list[CallRecord]:
    """Oldest first. A missing file is just "no calls yet"; a corrupt line
    (a half-written append from a crash, say) is skipped rather than taking
    the whole dashboard down — the same defensive read `usage_guard.py`
    applies to its own on-disk state."""
    p = path or config.CALL_LOG_FILE
    records: list[CallRecord] = []
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return records
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            records.append(CallRecord(**data))
        except (json.JSONDecodeError, TypeError):
            continue
    return records
