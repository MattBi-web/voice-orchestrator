import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENTS_FILE = Path(os.environ.get("VOICE_ORCH_AGENTS_FILE", ROOT / "config" / "agents.yaml"))
KNOWLEDGE_DIR = Path(os.environ.get("VOICE_ORCH_KNOWLEDGE_DIR", ROOT / "data" / "knowledge"))

ANTHROPIC_MODEL = os.environ.get("VOICE_ORCH_ANTHROPIC_MODEL", "claude-sonnet-4-5")
OPENAI_MODEL = os.environ.get("VOICE_ORCH_OPENAI_MODEL", "gpt-4.1-mini")
GEMINI_MODEL = os.environ.get("VOICE_ORCH_GEMINI_MODEL", "gemini-3-flash")

# Which provider to use: "anthropic" | "openai" | "gemini" | "fake" (default, zero setup).
PROVIDER = os.environ.get("VOICE_ORCH_PROVIDER", "fake")
