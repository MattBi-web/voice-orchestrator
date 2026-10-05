import os
from pathlib import Path


def _env_float(name: str, default: float) -> float:
    """An env var that's set but empty (a `.env` line like `NAME=` sourced
    with `set -a`) counts as unset — `os.environ.get(name, default)` alone
    returns "" in that case and `float("")` crashes the whole import."""
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else default


ROOT = Path(__file__).resolve().parents[2]
AGENTS_FILE = Path(os.environ.get("VOICE_ORCH_AGENTS_FILE", ROOT / "config" / "agents.yaml"))
KNOWLEDGE_DIR = Path(os.environ.get("VOICE_ORCH_KNOWLEDGE_DIR", ROOT / "data" / "knowledge"))
# Which external MCP servers an agent's "mcp:<name>" tools connect to —
# config, not code, same as agents.yaml. Missing file = no MCP tools registered.
MCP_SERVERS_FILE = Path(os.environ.get("VOICE_ORCH_MCP_SERVERS_FILE", ROOT / "config" / "mcp_servers.yaml"))
# Blocco 3 — custom HTTP webhook tools (tools/webhook_tool.py), an agent's
# "webhook:<name>" tools. Same "config, not code" shape as MCP_SERVERS_FILE
# above; missing file = no webhook tools registered.
WEBHOOK_TOOLS_FILE = Path(os.environ.get("VOICE_ORCH_WEBHOOK_TOOLS_FILE", ROOT / "config" / "webhook_tools.yaml"))
# Append-only log of webhook tool executions (tools/webhook_log.py) — the
# "log delle esecuzioni dei tool" blocco 3 asks for, read back by the agent
# builder's own tab. Same JSONL shape as CALL_LOG_FILE below, same reason.
WEBHOOK_LOG_FILE = Path(os.environ.get("VOICE_ORCH_WEBHOOK_LOG_FILE", ROOT / "data" / "webhook_log.jsonl"))

ANTHROPIC_MODEL = os.environ.get("VOICE_ORCH_ANTHROPIC_MODEL", "claude-sonnet-4-5")
OPENAI_MODEL = os.environ.get("VOICE_ORCH_OPENAI_MODEL", "gpt-4.1-mini")
GEMINI_MODEL = os.environ.get("VOICE_ORCH_GEMINI_MODEL", "gemini-3-flash")

# Which provider to use: "anthropic" | "openai" | "gemini" | "fake" (default, zero setup).
PROVIDER = os.environ.get("VOICE_ORCH_PROVIDER", "fake")

# Self-imposed daily cap on real-time voice minutes (voice/usage_guard.py) —
# none of LiveKit Cloud, Deepgram, ElevenLabs, or a host like Render offer a
# hard spending cap of their own, so the worker enforces one on itself
# instead of trusting a provider dashboard's after-the-fact email warning.
# 60 min/day is a deliberately small default for a portfolio demo, not a
# production sizing — raise it with this env var once you trust the setup.
MAX_CALL_MINUTES_PER_DAY = _env_float("VOICE_ORCH_MAX_CALL_MINUTES_PER_DAY", 60.0)
USAGE_FILE = Path(os.environ.get("VOICE_ORCH_USAGE_FILE", ROOT / "data" / "usage_log.json"))

# The web agent-builder's own store (webapi/). Deliberately separate from
# AGENTS_FILE above: the CLI/tests keep reading config/agents.yaml exactly as
# before (nothing about the existing, already-tested text core changes), and
# the web API owns this SQLite file as the canonical copy an editor UI can
# safely read-modify-write. A one-time import (webapi/seed.py) copies
# agents.yaml's family into this database the first time it's empty — see
# the README's "Agent builder" section for the two-sources-of-truth trade-off
# this implies.
WEBAPI_DB_FILE = Path(os.environ.get("VOICE_ORCH_WEBAPI_DB_FILE", ROOT / "data" / "agents.db"))

# Blocco 6 — "shared mode". Unset (the default): everything works exactly as
# before — the builder's SQLite file above, plus plain files for the call
# log, webhook log, usage tally and knowledge documents, so the CLI and the
# test suite need no database at all. Set (a SQLAlchemy URL; Render's
# `postgres://…` form is accepted): that one database holds *everything*,
# because the web service and the voice worker run on different machines
# and share nothing else — the worker reads the agent family, tools and
# knowledge from it and writes calls and usage back to it. Needs the
# `webapi` extra (sqlalchemy) and, for Postgres, the `postgres` extra.
DATABASE_URL = os.environ.get("VOICE_ORCH_DATABASE_URL", "").strip()


def shared_mode() -> bool:
    """Read at call time (not import time) so tests can flip it."""
    return bool(DATABASE_URL)

# Read directly here too (not just by livekit-agents' own CLI) so the
# webapi's live voice test console (webapi/voice_token.py) can mint a room
# token without needing the full voice/worker.py import chain.
LIVEKIT_URL = os.environ.get("LIVEKIT_URL", "")
# This project's docs and .env.example call it ELEVENLABS_API_KEY; the
# livekit ElevenLabs plugin only looks for ELEVEN_API_KEY on its own. Accept
# both, and pass it explicitly (voice/agent.py's elevenlabs_tts()) — D12
# found the worker crashing on a fresh .env that only set the documented one.
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY") or os.environ.get("ELEVEN_API_KEY", "")
LIVEKIT_API_KEY = os.environ.get("LIVEKIT_API_KEY", "")
LIVEKIT_API_SECRET = os.environ.get("LIVEKIT_API_SECRET", "")

# A durable, append-only log of finished calls (call_log.py) — one JSON line
# per call, written by `chat`, the voice worker, and the webapi's test-route
# endpoint, read back by the agent-builder's analytics dashboard
# (webapi/app.py's GET /api/calls*). Plain JSONL, not SQLite, so the text
# core and the voice worker keep needing zero extra dependencies to write to
# it — see call_log.py's module docstring.
CALL_LOG_FILE = Path(os.environ.get("VOICE_ORCH_CALL_LOG_FILE", ROOT / "data" / "call_log.jsonl"))
