"""A self-imposed daily cap on real-time voice minutes.

Why this exists: none of LiveKit Cloud, Deepgram, or ElevenLabs offer a hard
spending cap of their own, and if this worker ever runs on a host like
Render instead of a laptop, Render's support has confirmed the same thing —
no spend limit, only after-the-fact overage billing with an email warning
once you're close to it (see the README's "Voice layer" section for the
detail). `UsageGuard` is this project's own answer to that gap: it tracks
total call minutes per calendar day in a small JSON file on disk, and
`worker.py`'s `request_fnc` refuses a *new* call once the day's budget is
spent — the one thing that actually stops further usage, rather than a
log line nobody's watching in real time.

Call-minutes, not a per-provider euro estimate, is the metric on purpose: a
euro figure needs Deepgram/ElevenLabs/Anthropic's current per-unit prices
hardcoded here, which drift and go stale silently (exactly the kind of
confident-but-wrong number this project's README argues against elsewhere).
Minutes is a direct, provider-agnostic proxy for "how much STT/TTS/transport
did today's testing actually use" that needs no pricing assumptions at all.

A call already in progress when the cap is hit is left to finish — "block
new calls" was the explicit choice, not "hang up on someone mid-sentence."
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .. import config


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


@dataclass
class UsageState:
    date: str  # YYYY-MM-DD, UTC
    minutes: float


class UsageGuard:
    """One of these per worker process (not per call). `path` defaults to
    `config.USAGE_FILE` so every call on the same machine shares one day's
    tally and survives a worker restart within the same day; tests pass
    their own `path` (a tmp_path file) so they never touch the real one."""

    def __init__(self, max_minutes_per_day: float | None = None, path: Path | None = None):
        self.max_minutes_per_day = (
            max_minutes_per_day if max_minutes_per_day is not None else config.MAX_CALL_MINUTES_PER_DAY
        )
        # Shared mode (blocco 6) keeps the tally in the database, so the cap
        # holds across worker processes and restarts on other machines; an
        # explicit `path` (tests) always means the file.
        self._shared = path is None and config.shared_mode()
        self.path = path or config.USAGE_FILE

    def _read(self) -> UsageState:
        today = _today()
        if self._shared:
            from ..webapi import stores

            return UsageState(date=today, minutes=stores.usage_minutes(today))
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("date") == today:
                return UsageState(date=today, minutes=float(data.get("minutes", 0.0)))
        except (FileNotFoundError, json.JSONDecodeError, ValueError, TypeError):
            pass
        # No file, a corrupt file, or yesterday's (or any other day's) tally
        # all mean "today starts at zero" — this is a safety net, not a
        # ledger, so a bad file should never crash the worker.
        return UsageState(date=today, minutes=0.0)

    def _write(self, state: UsageState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"date": state.date, "minutes": state.minutes}), encoding="utf-8")

    def minutes_used_today(self) -> float:
        return self._read().minutes

    def can_start_call(self) -> bool:
        """Checked once, before a call is accepted — see worker.py's
        `request_fnc`. Not re-checked mid-call; see the module docstring."""
        return self._read().minutes < self.max_minutes_per_day

    def record_call(self, duration_seconds: float) -> None:
        """Called once a call ends (worker.py's shutdown callback), with how
        long it actually ran. Re-reads before writing, rather than trusting
        an in-memory total, so two calls finishing close together don't
        clobber each other's update."""
        if self._shared:
            from ..webapi import stores

            stores.usage_add(_today(), max(duration_seconds, 0.0) / 60.0)
            return
        state = self._read()
        state.minutes += max(duration_seconds, 0.0) / 60.0
        self._write(state)
