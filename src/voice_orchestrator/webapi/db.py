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

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .. import config
from .models import Base


def make_engine(db_file: Path | None = None):
    path = db_file or config.WEBAPI_DB_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sync_columns(engine)
    return engine


def _sql_literal(value) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def sync_columns(engine: Engine) -> list[str]:
    """Additive schema sync — the gap `create_all()` leaves. `create_all()`
    creates missing *tables* but never touches an existing one, so a
    database created before blocco 2/4 (or before D11's criterion kinds)
    lacks the columns the models now map, and every query on that table
    fails with "no such column". This adds each missing column, with the
    model's scalar default as its SQL default so existing rows get a value.

    The one non-additive step: a column the model no longer maps that is
    NOT NULL with no SQL default (e.g. the pre-blocco-2 `agents.voice`,
    superseded by `voice_id`) makes every INSERT from the current model
    fail, so it's dropped. Orphaned columns that are nullable or defaulted
    are harmless and left alone. Still not a migration framework (see
    models.py) — just enough that an older local DB keeps working.
    Returns the statements it ran, for tests and for the log."""
    inspector = inspect(engine)
    ran: list[str] = []
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {c["name"]: c for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                col_type = column.type.compile(dialect=engine.dialect)
                default = column.default.arg if column.default is not None and column.default.is_scalar else None
                if default is not None:
                    stmt = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type} NOT NULL DEFAULT {_sql_literal(default)}'
                else:
                    stmt = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'
                conn.execute(text(stmt))
                ran.append(stmt)
            mapped = {c.name for c in table.columns}
            for name, info in existing.items():
                if name in mapped or info.get("nullable", True) or info.get("default") is not None:
                    continue
                stmt = f'ALTER TABLE "{table.name}" DROP COLUMN "{name}"'
                conn.execute(text(stmt))
                ran.append(stmt)
    return ran


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
