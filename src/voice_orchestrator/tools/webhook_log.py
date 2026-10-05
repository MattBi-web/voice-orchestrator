"""A durable, append-only log of webhook tool executions — one JSON line per
call to a custom HTTP tool (`webhook_tool.py`), independent of
`call_log.py`'s whole-call record so the agent builder's "log esecuzioni
tool" tab can show "last N webhook calls, what they returned, how long they
took" without parsing every call's full transcript for the one tool it
cares about.

Same plain-JSONL, stdlib-only shape as `call_log.py`, for the same reason:
`webhook_tool.py` (and anything that imports it — `orchestrator.py`, the
CLI, the voice worker) must stay installable with none of `webapi`'s
sqlalchemy/fastapi — see `call_log.py`'s module docstring, which this
mirrors line for line.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import config


@dataclass
class Execution:
    tool_name: str
    call_id: str
    agent_id: str
    url: str
    method: str
    ok: bool
    status_code: int | None
    latency_ms: float
    error: str = ""
    at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _shared_store():
    """Shared mode (blocco 6): same lazy switch to the database as
    call_log._shared_store()."""
    if not config.shared_mode():
        return None
    from ..webapi import stores

    return stores


def append(execution: Execution, path: Path | None = None) -> None:
    if path is None and (store := _shared_store()):
        store.webhook_append(execution.as_dict())
        return
    p = path or config.WEBHOOK_LOG_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(execution.as_dict()) + "\n")


def read_all(path: Path | None = None) -> list[Execution]:
    """Oldest first. A missing file is just "no executions yet"; a corrupt
    line (a half-written append from a crash, say) is skipped rather than
    taking the whole dashboard down — same defensive read as
    `call_log.read_all()`."""
    if path is None and (store := _shared_store()):
        out = []
        for data in store.webhook_all():
            try:
                out.append(Execution(**data))
            except TypeError:
                continue
        return out
    p = path or config.WEBHOOK_LOG_FILE
    out: list[Execution] = []
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(Execution(**json.loads(line)))
        except (json.JSONDecodeError, TypeError):
            continue
    return out
