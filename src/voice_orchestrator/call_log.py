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

Each record also carries the full transcript (`turns`), with the routing
decision attached to every caller turn and the tools that fired attached to
every agent reply — the per-turn "why did it go there" view the
conversation detail page shows, and what `analysis.py` judges. Lines written
before `turns` existed simply load with an empty transcript.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config
from .observability import COMPONENT_AGENT, COMPONENT_TOOL, EVENT_HANDOFF, EVENT_TOOL_TRIGGERED
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
    # [{"speaker", "text", "agent_id", "timestamp", "routing"?, "handoff"?, "tools"?}]
    # — see transcript_from_session(). Default [] keeps pre-transcript lines loadable.
    turns: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary_dict(self) -> dict[str, Any]:
        """Everything but the transcript — what list views need, without
        shipping every call's full text just to render a table row."""
        data = self.as_dict()
        data.pop("turns", None)
        return data


def transcript_from_session(session: CallSession) -> list[dict[str, Any]]:
    """`full_log` turned into a JSON-friendly transcript, with each exchange's
    context attached where a reader would look for it:

    - caller turn  → `routing` (the RoutingEvent for that utterance) and
      `handoff` (if routing moved the call to another agent);
    - agent turn   → `tools` (ids of the tools that fired to ground that reply).

    The pairing needs no new bookkeeping in the orchestrator: `route()`
    records exactly one RoutingEvent per `handle_turn()` (every exit path
    goes through `router._record`), so the i-th caller turn pairs with
    `routing_log[i]`; handoff/tool events are bucketed by time into the
    window between a caller turn and the next one."""
    caller_turns = [t for t in session.full_log if t.speaker == "caller"]
    caller_windows: list[tuple[datetime, datetime | None]] = []
    for i, turn in enumerate(caller_turns):
        start = datetime.fromisoformat(turn.timestamp)
        end = datetime.fromisoformat(caller_turns[i + 1].timestamp) if i + 1 < len(caller_turns) else None
        caller_windows.append((start, end))

    def _events_in(window: tuple[datetime, datetime | None], component: str, event: str) -> list[dict[str, Any]]:
        start, end = window
        return [
            e.attributes
            for e in session.event_log
            if e.component == component and e.event == event and e.occurred_at >= start and (end is None or e.occurred_at < end)
        ]

    out: list[dict[str, Any]] = []
    caller_index = -1
    for turn in session.full_log:
        entry: dict[str, Any] = {
            "speaker": turn.speaker,
            "text": turn.text,
            "agent_id": turn.agent_id,
            "timestamp": turn.timestamp,
        }
        if turn.speaker == "caller":
            caller_index += 1
            if caller_index < len(session.routing_log):
                r = session.routing_log[caller_index]
                entry["routing"] = {
                    "resolved_by": r.resolved_by,
                    "chosen_agent": r.chosen_agent,
                    "eligible_agents": list(r.eligible_agents),
                    "latency_ms": round(r.latency_ms, 3),
                    "reason": r.reason,
                }
            handoffs = _events_in(caller_windows[caller_index], COMPONENT_AGENT, EVENT_HANDOFF)
            if handoffs:
                entry["handoff"] = {"from_agent": handoffs[0].get("from_agent"), "to_agent": handoffs[0].get("to_agent")}
        elif caller_index >= 0:
            tools = _events_in(caller_windows[caller_index], COMPONENT_TOOL, EVENT_TOOL_TRIGGERED)
            entry["tools"] = [str(t.get("tool_id", "?")) for t in tools]
        out.append(entry)
    return out


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
        turns=transcript_from_session(session),
    )


def _shared_store():
    """Blocco 6: in shared mode the log lives in the database (web service
    and voice worker are different machines). Imported lazily so the
    default file mode never needs sqlalchemy. An explicit `path` always
    means the file — that's what tests and tools passing one want."""
    if not config.shared_mode():
        return None
    from .webapi import stores

    return stores


def append(record: CallRecord, path: Path | None = None) -> None:
    if path is None and (store := _shared_store()):
        store.calls_append(record.as_dict())
        return
    p = path or config.CALL_LOG_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record.as_dict()) + "\n")


def read_all(path: Path | None = None) -> list[CallRecord]:
    """Oldest first. A missing file is just "no calls yet"; a corrupt line
    (a half-written append from a crash, say) is skipped rather than taking
    the whole dashboard down — the same defensive read `usage_guard.py`
    applies to its own on-disk state."""
    if path is None and (store := _shared_store()):
        return [r for r in (_load(d) for d in store.calls_all()) if r is not None]
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


def find(call_id: str, path: Path | None = None) -> CallRecord | None:
    """The most recent record with this id (ids are unique per call in
    practice; "most recent" just makes a duplicate harmless)."""
    if path is None and (store := _shared_store()):
        data = store.calls_find(call_id)
        return _load(data) if data else None
    for record in reversed(read_all(path)):
        if record.call_id == call_id:
            return record
    return None


def _load(data: dict[str, Any]) -> CallRecord | None:
    try:
        return CallRecord(**data)
    except TypeError:
        return None

