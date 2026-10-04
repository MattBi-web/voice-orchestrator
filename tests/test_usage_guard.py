"""Tests for the self-imposed daily call-minutes cap (voice/usage_guard.py).
No livekit-agents import needed — UsageGuard is pure file + arithmetic, so
these run with zero extra dependencies, same as test_voice_bridge.py."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from voice_orchestrator.voice.usage_guard import UsageGuard, _today


def test_fresh_guard_allows_calls_and_starts_at_zero(tmp_path):
    guard = UsageGuard(max_minutes_per_day=10, path=tmp_path / "usage.json")
    assert guard.minutes_used_today() == 0.0
    assert guard.can_start_call() is True


def test_record_call_accumulates_minutes(tmp_path):
    guard = UsageGuard(max_minutes_per_day=10, path=tmp_path / "usage.json")
    guard.record_call(duration_seconds=90)  # 1.5 minutes
    guard.record_call(duration_seconds=30)  # 0.5 minutes
    assert guard.minutes_used_today() == 2.0


def test_can_start_call_becomes_false_once_cap_is_reached(tmp_path):
    guard = UsageGuard(max_minutes_per_day=5, path=tmp_path / "usage.json")
    guard.record_call(duration_seconds=5 * 60)  # exactly the cap
    assert guard.can_start_call() is False


def test_a_call_in_progress_is_not_retroactively_blocked():
    """The guard only ever gates *new* calls (can_start_call, checked in
    request_fnc before accepting a job) — recording a call that pushed the
    day over budget doesn't raise or reject anything by itself."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        guard = UsageGuard(max_minutes_per_day=1, path=Path(d) / "usage.json")
        guard.record_call(duration_seconds=10 * 60)  # way over a 1-minute cap
        assert guard.minutes_used_today() == 10.0
        assert guard.can_start_call() is False  # the *next* call is what gets blocked


def test_resets_on_a_new_calendar_day(tmp_path):
    path = tmp_path / "usage.json"
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    path.write_text(json.dumps({"date": yesterday, "minutes": 999.0}), encoding="utf-8")

    guard = UsageGuard(max_minutes_per_day=10, path=path)

    assert guard.minutes_used_today() == 0.0
    assert guard.can_start_call() is True


def test_missing_or_corrupt_file_is_treated_as_zero_not_a_crash(tmp_path):
    path = tmp_path / "usage.json"
    guard = UsageGuard(max_minutes_per_day=10, path=path)
    assert guard.minutes_used_today() == 0.0  # file doesn't exist yet

    path.write_text("{not valid json", encoding="utf-8")
    assert guard.minutes_used_today() == 0.0  # corrupt file, not a crash


def test_today_is_a_utc_date_string():
    assert _today() == datetime.now(timezone.utc).strftime("%Y-%m-%d")
