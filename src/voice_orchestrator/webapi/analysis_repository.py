"""Storage for post-call analysis: the family-wide criteria / data-collection
config, and the latest `analysis.AnalysisResult` per call. Converts between
the SQLite rows (`models.py`) and the core's plain dataclasses
(`analysis.py`), so `analysis.analyze()` never sees SQLAlchemy at all.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..analysis import DATA_TYPES, KIND_LLM, KIND_TOOL_NOT_USED, KIND_TOOL_USED, KINDS, AnalysisResult, DataCollectionItem, EvaluationCriterion
from .models import CallAnalysisRow, DataCollectionItemRow, EvaluationCriterionRow

_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


class InvalidAnalysisConfig(ValueError):
    pass


def get_config(session: Session) -> tuple[list[EvaluationCriterion], list[DataCollectionItem]]:
    crit_rows = session.scalars(select(EvaluationCriterionRow).order_by(EvaluationCriterionRow.position)).all()
    item_rows = session.scalars(select(DataCollectionItemRow).order_by(DataCollectionItemRow.position)).all()
    return (
        [
            EvaluationCriterion(id=r.id, name=r.name, prompt=r.prompt, kind=r.kind or KIND_LLM, expected=json.loads(r.expected_json or "[]"))
            for r in crit_rows
        ],
        [DataCollectionItem(id=r.id, type=r.type, description=r.description) for r in item_rows],
    )


def _validate(criteria: list[EvaluationCriterion], items: list[DataCollectionItem]) -> None:
    for label, ids in (("criterio", [c.id for c in criteria]), ("campo", [d.id for d in items])):
        for id_ in ids:
            if not _ID_RE.match(id_):
                raise InvalidAnalysisConfig(f"Id {label} non valido: {id_!r} (solo lettere, numeri, _ e -)")
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise InvalidAnalysisConfig(f"Id {label} duplicato: {', '.join(sorted(dupes))}")
    for c in criteria:
        if c.kind not in KINDS:
            raise InvalidAnalysisConfig(f"Tipo di criterio non valido per {c.id!r}: {c.kind!r}")
        if c.kind == KIND_LLM and not c.prompt.strip():
            raise InvalidAnalysisConfig(f"Il criterio {c.id!r} non ha una descrizione di cosa significa successo")
        if c.kind in (KIND_TOOL_USED, KIND_TOOL_NOT_USED) and not [e for e in c.expected if e.strip()]:
            raise InvalidAnalysisConfig(f"Il criterio {c.id!r} deve indicare almeno un tool")
    for d in items:
        if d.type not in DATA_TYPES:
            raise InvalidAnalysisConfig(f"Tipo non valido per {d.id!r}: {d.type!r}")


def replace_config(session: Session, criteria: list[EvaluationCriterion], items: list[DataCollectionItem]) -> None:
    """Whole-list replace, the shape a single settings form saves in. Existing
    analyses are left alone: they record what was judged at the time, and
    re-running one is an explicit action, not a side effect of editing."""
    _validate(criteria, items)
    session.execute(delete(EvaluationCriterionRow))
    session.execute(delete(DataCollectionItemRow))
    for i, c in enumerate(criteria):
        session.add(criterion_row(c, i))
    for i, d in enumerate(items):
        session.add(DataCollectionItemRow(id=d.id, type=d.type, description=d.description, position=i))
    session.flush()


def criterion_row(c: EvaluationCriterion, position: int) -> EvaluationCriterionRow:
    return EvaluationCriterionRow(
        id=c.id,
        name=c.name,
        prompt=c.prompt,
        position=position,
        kind=c.kind,
        expected_json=json.dumps([e.strip() for e in c.expected if e.strip()]),
    )


def save_analysis(session: Session, call_id: str, result: AnalysisResult) -> CallAnalysisRow:
    row = session.get(CallAnalysisRow, call_id) or CallAnalysisRow(call_id=call_id)
    row.analyzed_at = datetime.now(timezone.utc).isoformat()
    row.method = result.method
    row.provider = result.provider
    row.call_successful = result.call_successful
    row.result_json = json.dumps(result.as_dict())
    session.add(row)
    session.flush()
    return row


def get_analysis(session: Session, call_id: str) -> CallAnalysisRow | None:
    return session.get(CallAnalysisRow, call_id)


def analysis_out(row: CallAnalysisRow) -> dict:
    data = json.loads(row.result_json or "{}")
    data["analyzed_at"] = row.analyzed_at
    return data


def verdicts_by_call(session: Session) -> dict[str, str]:
    """call_id -> call_successful, for list views and the dashboard's stats."""
    return {row.call_id: row.call_successful for row in session.scalars(select(CallAnalysisRow)).all()}
