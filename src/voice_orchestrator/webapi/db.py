"""Engine/session setup for the web agent-builder's SQLite database.

Two sources of truth now exist side by side, and that's worth being
explicit about rather than quietly papering over: `config/agents.yaml`
remains exactly what it was — what the CLI (`voice-orchestrator chat` /
`route` / `eval` / `agents list`) and the whole existing test suite read.
This module's database is a *separate* copy, owned by the web API, seeded
once from that same YAML (see `seed.py`) and then edited independently
through the browser from then on. Editing an agent in the web UI does not
change `agents.yaml`, and editing `agents.yaml` by hand does not change
this database. Unifying them — making the CLI read from SQLite too, or
exporting the DB back to YAML — is a reasonable next step if the web UI
becomes the primary way agents get authored, but it's explicitly not done
here: it would mean changing the already-tested CLI/registry code path to
make the newer, less-tested piece feel more finished, which is the wrong
order of operations.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .. import config
from .models import Base


def make_engine(db_file: Path | None = None):
    path = db_file or config.WEBAPI_DB_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return engine


_engine = make_engine()
_SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)


def configure(db_file: Path) -> None:
    """Point this module at a different database file — used by tests to
    get a throwaway DB per test instead of touching the real one."""
    global _engine, _SessionLocal
    _engine = make_engine(db_file)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency form of `session_scope` (a generator, not a context
    manager) — see `Depends(get_session)` in `app.py`."""
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
