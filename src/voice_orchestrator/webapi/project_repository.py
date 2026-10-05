"""Projects (blocco 8): create from a template, list, edit settings, delete,
export. A project's agents live in `agents` under its id (repository.py).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import config
from ..agents.registry import family_to_dict, load_family_file
from ..project import DEFAULT_PROJECT, ModelSettings, slugify
from . import repository
from .models import AgentRow, ProjectRow

TEMPLATES_DIR = config.ROOT / "config" / "templates"


class ProjectNotFound(ValueError):
    pass


class UnknownTemplate(ValueError):
    pass


@dataclass
class Template:
    id: str
    name: str
    description: str
    path: Path
    agent_count: int


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def templates() -> list[Template]:
    """single, workflow (config/templates/) and the demo family itself."""
    out = []
    for tid, path in (("single", TEMPLATES_DIR / "single.yaml"), ("workflow", TEMPLATES_DIR / "workflow.yaml"), ("demo", config.AGENTS_FILE)):
        root, meta = load_family_file(path)
        info = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("template") or meta
        name = info.get("name", tid) if tid != "demo" else f"Copy of {meta.get('name', 'the demo')}"
        out.append(Template(tid, name, info.get("description", ""), path, sum(1 for _ in root.iter_subtree())))
    return out


def get(session: Session, project_id: str) -> ProjectRow:
    row = session.get(ProjectRow, project_id)
    if row is None:
        raise ProjectNotFound(project_id)
    return row


def settings_of(session: Session, project_id: str) -> ModelSettings:
    row = session.get(ProjectRow, project_id)
    return ModelSettings.from_dict(row.settings if row else {})


def summary(session: Session, row: ProjectRow) -> dict:
    agents = repository.project_rows(session, row.id)
    root = next((a for a in agents if a.parent_id is None), None)
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "kind": "workflow" if len(agents) > 1 else "single",
        "agent_count": len(agents),
        "root_agent": {"id": root.id, "name": root.name} if root else None,
        "settings": ModelSettings.from_dict(row.settings).as_dict(),
    }


def list_all(session: Session) -> list[ProjectRow]:
    return list(session.scalars(select(ProjectRow).order_by(ProjectRow.position, ProjectRow.created_at)).all())


def unique_id(session: Session, name: str) -> str:
    base = slugify(name)
    candidate, n = base, 2
    while session.get(ProjectRow, candidate) is not None:
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def create(session: Session, name: str, template: str = "single", description: str = "", project_id: str | None = None) -> ProjectRow:
    chosen = next((t for t in templates() if t.id == template), None)
    if chosen is None:
        raise UnknownTemplate(template)
    root, meta = load_family_file(chosen.path)
    pid = project_id or unique_id(session, name)
    count = session.scalar(select(func.count()).select_from(ProjectRow)) or 0
    row = ProjectRow(
        id=pid,
        name=name.strip() or chosen.name,
        description=description or (meta.get("description", "") if template == "demo" else ""),
        created_at=_now(),
        updated_at=_now(),
        position=count,
    )
    row.settings = ModelSettings.from_dict(meta.get("settings")).as_dict()
    session.add(row)
    repository.insert_subtree(session, pid, root)
    session.flush()
    return row


def update(session: Session, project_id: str, name: str, description: str, settings: dict) -> ProjectRow:
    row = get(session, project_id)
    row.name = name
    row.description = description
    row.settings = ModelSettings.from_dict(settings).as_dict()
    row.updated_at = _now()
    session.flush()
    return row


def touch(session: Session, project_id: str) -> None:
    row = session.get(ProjectRow, project_id)
    if row is not None:
        row.updated_at = _now()


def remove(session: Session, project_id: str) -> None:
    get(session, project_id)
    session.execute(delete(AgentRow).where(AgentRow.project_id == project_id))
    session.execute(delete(ProjectRow).where(ProjectRow.id == project_id))
    session.flush()


def export(session: Session, project_id: str) -> dict:
    """The project as the same YAML shape config/agents.yaml uses: a
    `project:` block plus the agent tree. What the Developer tab shows."""
    row = get(session, project_id)
    root = repository.build_tree(session, project_id)
    block = {"name": row.name, "description": row.description, "settings": _compact(row.settings)}
    return family_to_dict(root, block) if root else {"project": block}


def _compact(settings: dict) -> dict:
    defaults = ModelSettings().as_dict()
    full = ModelSettings.from_dict(settings).as_dict()
    return {k: v for k, v in full.items() if v not in ("", None) or defaults[k] not in ("", None)}


def ensure_demo(session: Session) -> bool:
    """Seed/migration step: the demo project's row, for a database whose
    agents predate projects (db.migrate_agents_to_projects put them under
    "demo"). Returns True when it created the row."""
    if session.get(ProjectRow, DEFAULT_PROJECT) is not None:
        return False
    has_agents = session.scalar(select(AgentRow.id).where(AgentRow.project_id == DEFAULT_PROJECT).limit(1)) is not None
    if not has_agents:
        return False
    _, meta = load_family_file(config.AGENTS_FILE)
    row = ProjectRow(
        id=DEFAULT_PROJECT,
        name=meta.get("name", "Demo"),
        description=meta.get("description", ""),
        created_at=_now(),
        updated_at=_now(),
        position=0,
    )
    row.settings = ModelSettings.from_dict(meta.get("settings")).as_dict()
    session.add(row)
    session.flush()
    return True
