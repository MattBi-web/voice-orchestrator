import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENTS_FILE = Path(os.environ.get("VOICE_ORCH_AGENTS_FILE", ROOT / "config" / "agents.yaml"))
KNOWLEDGE_DIR = Path(os.environ.get("VOICE_ORCH_KNOWLEDGE_DIR", ROOT / "data" / "knowledge"))
# Which external MCP servers an agent's "mcp:<name>" tools connect to —
# config, not code, same as agents.yaml. Missing file = no MCP tools registered.
MCP_SERVERS_FILE = Path(os.environ.get("VOICE_ORCH_MCP_SERVERS_FILE", ROOT / "config" / "mcp_servers.yaml"))

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
MAX_CALL_MINUTES_PER_DAY = float(os.environ.get("VOICE_ORCH_MAX_CALL_MINUTES_PER_DAY", "60"))
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

# Read directly here too (not just by livekit-agents' own CLI) so the
# webapi's live voice test console (webapi/voice_token.py) can mint a room
# token without needing the full voice/worker.py import chain.
LIVEKIT_URL = os.environ.get("LIVEKIT_URL", "")
LIVEKIT_API_KEY = os.environ.get("LIVEKIT_API_KEY", "")
LIVEKIT_API_SECRET = os.environ.get("LIVEKIT_API_SECRET", "")

# A durable, append-only log of finished calls (call_log.py) — one JSON line
# per call, written by `chat`, the voice worker, and the webapi's test-route
# endpoint, read back by the agent-builder's analytics dashboard
# (webapi/app.py's GET /api/calls*). Plain JSONL, not SQLite, so the text
# core and the voice worker keep needing zero extra dependencies to write to
# it — see call_log.py's module docstring.
CALL_LOG_FILE = Path(os.environ.get("VOICE_ORCH_CALL_LOG_FILE", ROOT / "data" / "call_log.jsonl"))
