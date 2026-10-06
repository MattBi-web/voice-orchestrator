"""Shared test setup.

`VOICE_ORCH_TEST_DATABASE_URL` (blocco 6): when set — e.g. to a throwaway
Postgres, `postgresql://user@localhost:5432/vo_test` — every test that uses
`configure_test_db()` runs in *shared mode* against that database instead
of a temporary SQLite file, with the schema dropped and recreated per test.
Unset (the default, and CI), nothing changes. tests/test_shared_mode.py
covers shared mode on every run regardless, with a SQLite URL.
"""
from __future__ import annotations

import os

import pytest

TEST_DATABASE_URL = os.environ.get("VOICE_ORCH_TEST_DATABASE_URL", "").strip()

# The suite must not depend on the developer's shell. Running it from the
# terminal that starts the server would otherwise switch on the owner
# password (401s), "configured" voice, shared mode and real model keys.
# config.py reads the environment at import time, so this runs before any
# voice_orchestrator import (conftest loads first).
_KEEP = {"VOICE_ORCH_TEST_DATABASE_URL"}
for _name in list(os.environ):
    if _name in _KEEP:
        continue
    if _name.startswith(("VOICE_ORCH_", "LIVEKIT_")) or _name.endswith("_API_KEY") or _name == "ELEVEN_API_KEY":
        del os.environ[_name]


@pytest.fixture(autouse=True)
def _restore_database():
    """A test that points the app at its own database must not leak it
    into the next test."""
    from voice_orchestrator.webapi import db

    engine, session_local = db._engine, db._SessionLocal
    yield
    db._engine, db._SessionLocal = engine, session_local

def reset_database(url: str) -> None:
    from sqlalchemy import create_engine

    from voice_orchestrator.webapi.db import normalize_url
    from voice_orchestrator.webapi.models import Base

    engine = create_engine(normalize_url(url))
    Base.metadata.drop_all(engine)
    engine.dispose()


def configure_test_db(tmp_path, monkeypatch, name: str = "test.db", url: str | None = None) -> None:
    """Throwaway database for one test: `url` (or VOICE_ORCH_TEST_DATABASE_URL)
    in shared mode, else a SQLite file under tmp_path in the default mode."""
    from voice_orchestrator import config
    from voice_orchestrator.webapi import db

    url = url or TEST_DATABASE_URL
    if url:
        monkeypatch.setattr(config, "DATABASE_URL", url)
        reset_database(url)
        db.configure(url)
    else:
        db.configure(tmp_path / name)
