"""Multi-turn text tests (blocco 7, fase B): the agent page's test panel
holds a conversation, not a single utterance, so a handover, the
specialist's follow-up and a goodbye can be tried in a row, the way a call
goes.

The CallSession lives here, in memory, between turns. That is enough for
one web process (the Render web service runs a single uvicorn worker) and
keeps the turn exact: slots set by a tool, the agent path and the history
carry over as they would on a call, instead of being rebuilt from a
transcript the client sends back. The family is re-read from the database
at each turn, so an edit saved mid-conversation is live on the next turn.

A conversation is written to the call log once, when it ends: the caller
says goodbye (end_call), the panel resets it, or it sits idle past IDLE_TTL
and is swept. It is recorded as `route_test`, like the single-turn box, so
Analytics can leave tests out. Limits keep a public demo from growing memory
without bound: MAX_LIVE conversations, MAX_TURNS each.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from datetime import datetime, timezone

from .. import call_events, call_log
from ..agents.registry import AgentSpec
from ..llm import FakeProvider, LLMProvider
from ..orchestrator import handle_turn
from ..project import DEFAULT_PROJECT
from ..state import CallSession

IDLE_TTL = 30 * 60
MAX_LIVE = 200
MAX_TURNS = 40


class ConversationGone(Exception):
    """Unknown id: never existed, already ended, or swept after IDLE_TTL."""


class ConversationFull(Exception):
    pass


@dataclass
class Conversation:
    session: CallSession
    provider: LLMProvider
    started_at: datetime
    responder: Any = None
    project_id: str = DEFAULT_PROJECT
    simulated: bool = True
    touched: float = field(default_factory=time.monotonic)
    seq: int = 0


_live: dict[str, Conversation] = {}
_lock = threading.Lock()


def _log(conv: Conversation) -> None:
    if conv.session.full_log:
        call_log.append(
            call_log.from_session(conv.session, source="route_test", started_at=conv.started_at, project_id=conv.project_id)
        )


def _sweep(now: float) -> None:
    for cid in [c for c, conv in _live.items() if now - conv.touched > IDLE_TTL]:
        _log(_live.pop(cid))


def start(
    start_path: list[str],
    channel: str,
    slots: dict,
    provider: LLMProvider,
    responder: Any = None,
    project_id: str = DEFAULT_PROJECT,
    simulated: bool | None = None,
) -> str:
    cid = f"webapi-conv-{uuid.uuid4().hex[:8]}"
    session = CallSession(call_id=cid, channel=channel, slots=dict(slots))
    session.agent_path = list(start_path)
    with _lock:
        _sweep(time.monotonic())
        if len(_live) >= MAX_LIVE:
            raise ConversationFull("Too many test conversations open right now; try again in a few minutes.")
        _live[cid] = Conversation(
            session=session,
            provider=provider,
            started_at=datetime.now(timezone.utc),
            responder=responder,
            project_id=project_id,
            simulated=isinstance(provider, FakeProvider) if simulated is None else simulated,
        )
    return cid


def turn(cid: str, root: AgentSpec, utterance: str, slots: dict | None = None) -> dict:
    """One caller turn. Returns the same event a live call publishes
    (call_events.turn_event), plus `ended` when end_call ran."""
    with _lock:
        conv = _live.get(cid)
        if conv is None:
            raise ConversationGone(cid)
        conv.touched = time.monotonic()
    if conv.seq >= MAX_TURNS:
        raise ConversationFull(f"A test conversation stops at {MAX_TURNS} turns; start a new one.")
    session = conv.session
    if slots:
        session.slots.update(slots)
    # The agent that had the call may have been deleted or moved in the
    # builder since the last turn: carry on from the top rather than fail.
    if session.current_agent_id and root.find(session.current_agent_id) is None:
        session.agent_path = [root.id]
    from_id = session.current_agent_id or root.id
    result = handle_turn(session, root, utterance, conv.provider, responder=conv.responder)
    conv.seq += 1
    event = call_events.turn_event(root, from_id, utterance, result, session, conv.seq, simulated=conv.simulated)
    ended = "end_call" in result.tool_ids_used
    if ended:
        end(cid)
    return {**event, "ended": ended}


def project_of(cid: str) -> str | None:
    with _lock:
        conv = _live.get(cid)
    return conv.project_id if conv else None


def end(cid: str) -> bool:
    with _lock:
        conv = _live.pop(cid, None)
    if conv is None:
        return False
    _log(conv)
    return True


def reset_for_tests() -> None:
    with _lock:
        _live.clear()
