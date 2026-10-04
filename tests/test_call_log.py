"""Tests for call_log.py — deliberately imports nothing from webapi/ or
voice/, proving the core (CLI, tests) can log calls with zero extra
dependencies, exactly the promise its module docstring makes.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from voice_orchestrator import call_log, observability
from voice_orchestrator.state import CallSession, RoutingEvent


def _session_with_a_turn() -> CallSession:
    session = CallSession(call_id="t1", channel="voice")
    session.agent_path = ["router", "billing"]
    session.add_turn("caller", "quanto devo pagare?")
    session.add_turn("agent", "ecco il saldo", agent_id="billing")
    return session


def test_from_session_captures_duration_turns_and_final_agent():
    session = _session_with_a_turn()
    started = datetime.now(timezone.utc) - timedelta(seconds=5)
    ended = started + timedelta(seconds=5)

    record = call_log.from_session(session, source="chat", started_at=started, ended_at=ended)

    assert record.call_id == "t1"
    assert record.source == "chat"
    assert record.channel == "voice"
    assert record.turn_count == 2
    assert record.final_agent_id == "billing"
    assert record.duration_seconds == 5.0


def test_from_session_counts_tool_triggers_from_event_log():
    session = _session_with_a_turn()
    session.record_event(observability.COMPONENT_TOOL, observability.EVENT_TOOL_TRIGGERED, tool_id="knowledge_lookup")
    session.record_event(observability.COMPONENT_TOOL, observability.EVENT_TOOL_TRIGGERED, tool_id="knowledge_lookup")
    session.record_event(observability.COMPONENT_TOOL, observability.EVENT_TOOL_TRIGGERED, tool_id="transfer_to_human")
    # A skipped-by-condition tool event must NOT count as triggered.
    session.record_event(observability.COMPONENT_TOOL, observability.EVENT_TOOL_SKIPPED_CONDITION, tool_id="check_account_status")

    record = call_log.from_session(session, source="chat", started_at=datetime.now(timezone.utc))

    assert record.tool_counts == {"knowledge_lookup": 2, "transfer_to_human": 1}


def test_from_session_captures_routing_and_handoff_counts():
    session = _session_with_a_turn()
    session.routing_log.append(
        RoutingEvent(utterance="x", resolved_by="pattern", chosen_agent="billing", eligible_agents=["billing"], latency_ms=0.1)
    )
    session.record_handoff(from_agent="router", to_agent="billing", reason="pattern match")

    record = call_log.from_session(session, source="voice", started_at=datetime.now(timezone.utc))

    assert record.resolved_by_counts["pattern"] == 1
    assert record.handoffs == 1


def test_append_then_read_all_round_trips(tmp_path):
    path = tmp_path / "call_log.jsonl"
    session = _session_with_a_turn()
    record = call_log.from_session(session, source="chat", started_at=datetime.now(timezone.utc))

    call_log.append(record, path=path)
    back = call_log.read_all(path=path)

    assert len(back) == 1
    assert back[0] == record


def test_read_all_appends_across_multiple_calls_oldest_first(tmp_path):
    path = tmp_path / "call_log.jsonl"
    for call_id in ("a", "b", "c"):
        session = CallSession(call_id=call_id, channel="chat")
        session.add_turn("caller", "ciao")
        record = call_log.from_session(session, source="chat", started_at=datetime.now(timezone.utc))
        call_log.append(record, path=path)

    back = call_log.read_all(path=path)
    assert [r.call_id for r in back] == ["a", "b", "c"]


def test_read_all_on_missing_file_is_empty_not_a_crash(tmp_path):
    assert call_log.read_all(path=tmp_path / "does_not_exist.jsonl") == []


def test_read_all_skips_a_corrupt_line_instead_of_crashing(tmp_path):
    path = tmp_path / "call_log.jsonl"
    session = _session_with_a_turn()
    good = call_log.from_session(session, source="chat", started_at=datetime.now(timezone.utc))
    call_log.append(good, path=path)
    with path.open("a", encoding="utf-8") as f:
        f.write("{not valid json\n")

    back = call_log.read_all(path=path)
    assert len(back) == 1
    assert back[0].call_id == good.call_id
