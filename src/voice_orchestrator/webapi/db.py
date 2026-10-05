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

import logging

from .. import config
from .models import Base

logger = logging.getLogger(__name__)


def normalize_url(url: str) -> str:
    """Render (and Heroku before it) hand out `postgres://…`; SQLAlchemy
    wants a dialect+driver. psycopg 3 is the driver the `postgres` extra
    installs."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def make_engine(target: Path | str | None = None):
    """`target`: a SQLAlchemy URL, a SQLite file path, or None — then
    config.DATABASE_URL if set (shared mode), else the builder's own SQLite
    file (config.WEBAPI_DB_FILE)."""
    if target is None:
        target = config.DATABASE_URL or config.WEBAPI_DB_FILE
    if isinstance(target, str) and "://" in target:
        url = normalize_url(target)
    else:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{path}"
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False})
    else:
        # pre_ping: a managed Postgres closes idle connections; without it
        # the first request after a quiet spell fails on a dead socket.
        engine = create_engine(url, pool_pre_ping=True, pool_recycle=300)
    migrate_agents_to_projects(engine)
    Base.metadata.create_all(engine)
    sync_columns(engine)
    return engine


def migrate_agents_to_projects(engine: Engine) -> bool:
    """Blocco 8: `agents` gained `project_id` as part of its primary key,
    which no additive ALTER can do. A database from before projects has its
    agents read into memory (a family is a handful of rows), the old table
    dropped, and the rows put back under the "demo" project once
    create_all() has made the new table. seed.py then gives "demo" its
    project row. Returns True when it migrated."""
    inspector = inspect(engine)
    if not inspector.has_table("agents"):
        return False
    old_columns = [c["name"] for c in inspector.get_columns("agents")]
    if "project_id" in old_columns:
        return False
    with engine.begin() as conn:
        rows = [dict(r._mapping) for r in conn.execute(text('SELECT * FROM "agents"'))]
        conn.execute(text('DROP TABLE "agents"'))
    Base.metadata.create_all(engine)
    sync_columns(engine)
    from .models import AgentRow

    mapped = {c.name for c in AgentRow.__table__.columns}
    with engine.begin() as conn:
        for row in rows:
            values = {k: v for k, v in row.items() if k in mapped}
            values["project_id"] = "demo"
            conn.execute(AgentRow.__table__.insert().values(**values))
    logger.warning("schema: moved %d agents under the 'demo' project (blocco 8)", len(rows))
    return True


def _sql_literal(value, dialect: str = "sqlite") -> str:
    if isinstance(value, bool):
        if dialect == "postgresql":
            return "TRUE" if value else "FALSE"
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
                    stmt = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type} NOT NULL DEFAULT {_sql_literal(default, engine.dialect.name)}'
                else:
                    stmt = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'
                conn.execute(text(stmt))
                ran.append(stmt)
            mapped = {c.name for c in table.columns}
            for name, info in existing.items():
                if name in mapped or info.get("nullable", True) or info.get("default") is not None:
                    continue
                stmt = f'ALTER TABLE "{table.name}" DROP COLUMN "{name}"'
                logger.warning("schema sync: dropping orphaned NOT NULL column %s.%s", table.name, name)
                conn.execute(text(stmt))
                ran.append(stmt)
    return ran


_engine = make_engine()
_SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)


def configure(target: Path | str) -> None:
    """Point this module at a different database (file path or URL) — used
    by tests to get a throwaway DB per test instead of touching the real one."""
    global _engine, _SessionLocal
    _engine.dispose()
    _engine = make_engine(target)
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
