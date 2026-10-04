"""Tests for call_log.py — deliberately imports nothing from webapi/ or
voice/, proving the core (CLI, tests) can log calls with zero extra
dependencies, exactly the promise its module docstring makes.
"""
from __future__ import annotations

import json
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


def test_transcript_attaches_routing_handoff_and_tools_from_a_real_call():
    """End to end through the real orchestrator (FakeProvider, the bundled
    agents.yaml): the transcript must say *why* each turn went where it did,
    not just what was said."""
    from voice_orchestrator import config
    from voice_orchestrator.agents.registry import load_family
    from voice_orchestrator.llm import FakeProvider
    from voice_orchestrator.orchestrator import handle_turn

    root = load_family(config.AGENTS_FILE)
    session = CallSession(call_id="t-transcript", channel="voice")
    handle_turn(session, root, "quanto costa il roaming dati in Francia?", FakeProvider())
    handle_turn(session, root, "grazie", FakeProvider())

    record = call_log.from_session(session, source="chat", started_at=datetime.now(timezone.utc))
    turns = record.turns

    assert [t["speaker"] for t in turns] == ["caller", "agent", "caller", "agent"]
    first_caller, first_agent, second_caller, second_agent = turns
    assert first_caller["routing"]["chosen_agent"] == "roaming"
    assert first_caller["routing"]["resolved_by"] in ("gate_only", "pattern", "llm_fallback")
    assert first_caller["handoff"] == {"from_agent": "router", "to_agent": "roaming"}
    assert first_agent["agent_id"] == "roaming"
    assert first_agent["tools"] == ["mcp:demo"]
    # Second turn: routing recorded again, no new handoff, and the tool from
    # turn 1 must not leak into turn 2's reply.
    assert "routing" in second_caller
    assert "handoff" not in second_caller
    assert "mcp:demo" not in second_agent["tools"]


def test_a_line_written_before_transcripts_existed_still_loads(tmp_path):
    path = tmp_path / "call_log.jsonl"
    legacy = {
        "call_id": "old", "source": "chat", "channel": "voice", "started_at": "2026-09-01T10:00:00+00:00",
        "ended_at": "2026-09-01T10:01:00+00:00", "duration_seconds": 60.0, "turn_count": 2,
        "final_agent_id": "billing", "resolved_by_counts": {}, "tool_counts": {}, "handoffs": 0,
    }
    path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")

    back = call_log.read_all(path=path)
    assert back[0].call_id == "old"
    assert back[0].turns == []


def test_find_and_summary_dict(tmp_path):
    path = tmp_path / "call_log.jsonl"
    record = call_log.from_session(_session_with_a_turn(), source="chat", started_at=datetime.now(timezone.utc))
    call_log.append(record, path=path)

    found = call_log.find("t1", path=path)
    assert found is not None and len(found.turns) == 2
    assert "turns" not in found.summary_dict()
    assert call_log.find("nope", path=path) is None
