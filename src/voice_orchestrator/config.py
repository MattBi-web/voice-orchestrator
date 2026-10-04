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
