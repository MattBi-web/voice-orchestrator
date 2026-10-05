"""Custom HTTP webhook tools — an agent author points at any REST endpoint
(URL, method, headers, a small set of parameters) and it becomes a Tool,
config-driven exactly like `mcp_tool.py`'s MCP servers, no code change
needed. This is the "webhook" half of the "tool dinamici" promise the
original brief made (see docs/ROADMAP.md's D5); `mcp_tool.py` is the other
half.

Same `should_trigger()` keyword-matching mechanism as every other tool here
— see `base.py`'s module docstring on why this project never uses native
LLM function-calling: an agent's trigger words decide whether a webhook
fires, not an LLM filling a JSON schema. The parameters this tool declares
(`WebhookParam`, the "parametri in JSON schema" the roadmap asks for) are
instead filled from exactly two places: a literal fixed at setup, or
`CallSession.slots` by name — the same "value already known by the call, or
hard-coded" shape `account_tool.py`'s mock lookup uses, kept here instead of
pretending a keyword-triggered tool can also have an LLM extract free-form
arguments from the utterance.

Secrets ("mai in chiaro nella UI"): a header value can reference
`{{secret:NAME}}`, resolved at call time from the `VOICE_ORCH_SECRET_<NAME>`
environment variable — never stored or shown anywhere in the web UI/DB in
cleartext, the same convention `config.py` already uses for
`LIVEKIT_API_SECRET`. A referenced secret that isn't set fails that one call
with a clear, loggable error instead of silently sending an empty header.

Every execution — success or failure — is appended to `webhook_log.jsonl`
(`webhook_log.py`) so the agent builder's "log esecuzioni tool" tab has
something to show, independent of whether the call also shows up in the
main call log.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml

from .. import config
from ..agents.registry import AgentSpec
from ..state import CallSession
from . import webhook_log
from .base import Tool, ToolResult

_SECRET_RE = re.compile(r"^\{\{secret:([A-Za-z0-9_]+)\}\}$")


@dataclass
class WebhookParam:
    name: str
    source: str = "slot"  # "slot" | "literal"
    value: str = ""  # slot name (source=="slot") or the literal itself (source=="literal")
    type: str = "string"  # "string" | "number" | "boolean" — coercion only, not strict validation


@dataclass
class WebhookToolConfig:
    """`name` is the tool id suffix — registered as "webhook:<name>", same
    "mcp:<name>" convention `mcp_tool.py`'s `MCPServerConfig` uses."""

    name: str
    description: str = ""
    url: str = ""
    method: str = "POST"
    headers: dict[str, str] = field(default_factory=dict)
    params: list[WebhookParam] = field(default_factory=list)
    triggers: tuple[str, ...] = ()
    timeout_seconds: float = 5.0


class SecretNotConfigured(RuntimeError):
    """Raised when a header references `{{secret:NAME}}` and
    `VOICE_ORCH_SECRET_NAME` isn't set in this process's environment."""


def resolve_header_value(raw: str) -> str:
    """"{{secret:NAME}}" -> `os.environ["VOICE_ORCH_SECRET_NAME"]`; anything
    else (a literal header value, e.g. "application/json") passes through
    unchanged. Raises SecretNotConfigured rather than silently sending an
    empty/wrong header when the env var isn't set."""
    m = _SECRET_RE.match(raw.strip())
    if not m:
        return raw
    env_name = f"VOICE_ORCH_SECRET_{m.group(1)}"
    value = os.environ.get(env_name)
    if not value:
        raise SecretNotConfigured(env_name)
    return value


def _coerce(raw: str, type_: str) -> Any:
    if type_ == "number":
        try:
            return float(raw) if "." in raw else int(raw)
        except ValueError:
            return raw
    if type_ == "boolean":
        return raw.strip().lower() in ("1", "true", "yes", "si", "sì")
    return raw


def _build_params(params: list[WebhookParam], session: CallSession) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for p in params:
        if not p.name:
            continue
        if p.source == "slot":
            raw = session.slots.get(p.value)
            if raw is None:
                continue
            out[p.name] = _coerce(raw, p.type) if isinstance(raw, str) else raw
        else:
            out[p.name] = _coerce(p.value, p.type)
    return out


class WebhookTool(Tool):
    """One Tool instance per configured webhook. `transport` is a test-only
    hook (an `httpx.MockTransport`, say) so `run()`'s real request-building
    code path can be exercised without a real socket — never set in
    production, where `httpx.Client`'s own default transport is used."""

    def __init__(self, cfg: WebhookToolConfig, *, transport: httpx.BaseTransport | None = None):
        self._cfg = cfg
        self._transport = transport
        self.id = f"webhook:{cfg.name}"
        self.description = cfg.description or f"Custom HTTP tool: {cfg.method} {cfg.url}"

    def should_trigger(self, agent: AgentSpec, utterance: str, session: CallSession) -> bool:
        if not self._cfg.triggers:
            return False
        text = utterance.lower()
        return any(re.search(re.escape(t.lower()), text) for t in self._cfg.triggers if t)

    def _log(
        self,
        *,
        session: CallSession,
        agent: AgentSpec,
        ok: bool,
        status_code: int | None,
        latency_ms: float,
        error: str = "",
    ) -> None:
        webhook_log.append(
            webhook_log.Execution(
                tool_name=self._cfg.name,
                call_id=session.call_id,
                agent_id=agent.id if agent is not None else "",
                url=self._cfg.url,
                method=self._cfg.method.upper(),
                ok=ok,
                status_code=status_code,
                latency_ms=round(latency_ms, 1),
                error=error,
            )
        )

    def run(self, agent: AgentSpec, utterance: str, session: CallSession) -> ToolResult:
        cfg = self._cfg
        started = time.monotonic()

        try:
            headers = {k: resolve_header_value(v) for k, v in cfg.headers.items()}
        except SecretNotConfigured as exc:
            self._log(session=session, agent=agent, ok=False, status_code=None, latency_ms=0.0, error=str(exc))
            return ToolResult(
                summary=(
                    f"Webhook tool '{cfg.name}' is misconfigured: the server environment variable "
                    f"{exc} is not set. Tell the caller this feature is temporarily unavailable; "
                    "don't invent a result."
                )
            )

        params = _build_params(cfg.params, session)
        method = cfg.method.upper()
        request_kwargs: dict[str, Any] = {"headers": headers}
        if method == "GET":
            request_kwargs["params"] = params
        else:
            request_kwargs["json"] = params

        try:
            with httpx.Client(transport=self._transport, timeout=cfg.timeout_seconds) as client:
                response = client.request(method, cfg.url, **request_kwargs)
            latency_ms = (time.monotonic() - started) * 1000
            ok = response.status_code < 400
            body_preview = response.text[:500]
            self._log(session=session, agent=agent, ok=ok, status_code=response.status_code, latency_ms=latency_ms)
            if ok:
                summary = (
                    f"[webhook:{cfg.name}] {method} {cfg.url} -> {response.status_code}. "
                    f"Response: {body_preview}. Answer the caller using exactly this data."
                )
            else:
                summary = (
                    f"[webhook:{cfg.name}] {method} {cfg.url} -> {response.status_code}. "
                    "This call failed — tell the caller briefly, don't invent a result."
                )
            return ToolResult(
                summary=summary,
                data={"status_code": response.status_code, "body": body_preview},
            )
        except httpx.HTTPError as exc:
            latency_ms = (time.monotonic() - started) * 1000
            self._log(session=session, agent=agent, ok=False, status_code=None, latency_ms=latency_ms, error=str(exc))
            return ToolResult(
                summary=(
                    f"Webhook tool '{cfg.name}' failed to reach {cfg.url}: {exc}. "
                    "Tell the caller this feature is temporarily unavailable; don't invent a result."
                )
            )


def read_raw_entries(path: Path = config.WEBHOOK_TOOLS_FILE) -> list[dict]:
    """The `tools:` list from config/webhook_tools.yaml, exactly as written.
    No file, empty file, or a parse error all mean "no webhook tools", not
    an error — mirrors `mcp_tool.read_raw_server_entries()`. Used both by
    `read_configs()` below and by `webapi/seed.py`."""
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return list(data.get("tools", []))
    except Exception:
        return []


def _parse_entry(entry: dict) -> WebhookToolConfig:
    headers = {str(k): str(v) for k, v in (entry.get("headers") or {}).items()}
    params = [
        WebhookParam(
            name=p["name"],
            source=p.get("source", "slot"),
            value=str(p.get("value", "")),
            type=p.get("type", "string"),
        )
        for p in entry.get("params", [])
    ]
    return WebhookToolConfig(
        name=entry["name"],
        description=entry.get("description", ""),
        url=entry.get("url", ""),
        method=entry.get("method", "POST"),
        headers=headers,
        params=params,
        triggers=tuple(entry.get("triggers", [])),
        timeout_seconds=float(entry.get("timeout_seconds", 5.0)),
    )


def read_configs(path: Path = config.WEBHOOK_TOOLS_FILE) -> list[WebhookToolConfig]:
    try:
        return [_parse_entry(e) for e in read_raw_entries(path)]
    except Exception:
        return []


def load_webhook_tools(path: Path = config.WEBHOOK_TOOLS_FILE) -> list[WebhookTool]:
    """One WebhookTool per configured entry — see `read_configs()`."""
    return [WebhookTool(cfg) for cfg in read_configs(path)]
