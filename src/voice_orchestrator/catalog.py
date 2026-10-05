"""Which providers and models the builder offers (blocco 8), and which of
them can actually run here.

Honest by construction: an entry is `available` only when its API key is
set on this server (and, for an LLM, its SDK is installed, since the web
service runs text tests itself). Everything else is still listed, marked
with what it needs, so the page shows the landscape without promising a
model that would silently fall back to a placeholder. Models are
suggestions: the builder also accepts a model id typed by hand.

Speech providers (STT/TTS) run on the voice worker, which is built from the
same image plus the `voice` extra; their keys are shared between the two
services (render.yaml), so checking the key here reflects the worker too.
"""
from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass, field


@dataclass
class Provider:
    component: str  # "stt" | "tts" | "llm"
    id: str
    label: str
    keys: tuple[str, ...]  # any one of these env vars is enough
    models: list[str]
    default_model: str
    sdk: str = ""  # importable module the web service needs (LLMs only)
    voices: list[dict] = field(default_factory=list)  # [{"id", "label"}], TTS only
    languages: list[str] = field(default_factory=list)  # STT only
    note: str = ""

    def key_set(self) -> bool:
        return any(os.environ.get(k) for k in self.keys)

    def installed(self) -> bool:
        return not self.sdk or importlib.util.find_spec(self.sdk) is not None

    def as_dict(self) -> dict:
        missing = []
        if not self.key_set():
            missing.append(f"needs {self.keys[0]}")
        if not self.installed():
            missing.append(f"needs the {self.sdk} package")
        return {
            "component": self.component,
            "id": self.id,
            "label": self.label,
            "models": self.models,
            "default_model": self.default_model,
            "voices": self.voices,
            "languages": self.languages,
            "available": not missing,
            "missing": "; ".join(missing),
            "note": self.note,
        }


ELEVENLABS_VOICES = [
    {"id": "", "label": "Default voice"},
    {"id": "21m00Tcm4TlvDq8ikWAM", "label": "Rachel (female, calm)"},
    {"id": "EXAVITQu4vr4xnSDxMaL", "label": "Sarah (female, soft)"},
    {"id": "pNInz6obpgDQGcFmaJgB", "label": "Adam (male, deep)"},
    {"id": "VR6AewLTigWG4xSOukaG", "label": "Arnold (male, crisp)"},
    {"id": "ErXwobaYiN019PkySvjV", "label": "Antoni (male, warm)"},
]

OPENAI_VOICES = [{"id": v, "label": v.capitalize()} for v in ("alloy", "ash", "coral", "echo", "sage", "shimmer", "verse")]

LANGUAGES = ["multi", "it", "en", "es", "fr", "de"]

PROVIDERS: list[Provider] = [
    # Speech to text
    Provider("stt", "deepgram", "Deepgram", ("DEEPGRAM_API_KEY",), ["nova-3", "nova-2"], "nova-3", languages=LANGUAGES,
             note="Streaming; nova-3 with language 'multi' switches languages mid-call."),
    Provider("stt", "openai", "OpenAI", ("OPENAI_API_KEY",), ["gpt-4o-mini-transcribe", "gpt-4o-transcribe", "whisper-1"],
             "gpt-4o-mini-transcribe", languages=LANGUAGES),
    Provider("stt", "assemblyai", "AssemblyAI", ("ASSEMBLYAI_API_KEY",),
             ["universal-streaming-multilingual", "universal-streaming-english"], "universal-streaming-multilingual",
             languages=["multi", "en"]),
    # Text to speech
    Provider("tts", "elevenlabs", "ElevenLabs", ("ELEVENLABS_API_KEY", "ELEVEN_API_KEY"),
             ["eleven_flash_v2_5", "eleven_turbo_v2_5", "eleven_multilingual_v2"], "eleven_flash_v2_5",
             voices=ELEVENLABS_VOICES, note="Flash v2.5 is the low-latency model; multilingual v2 sounds best but is slower."),
    Provider("tts", "openai", "OpenAI", ("OPENAI_API_KEY",), ["gpt-4o-mini-tts", "tts-1"], "gpt-4o-mini-tts", voices=OPENAI_VOICES),
    Provider("tts", "cartesia", "Cartesia", ("CARTESIA_API_KEY",), ["sonic-3", "sonic-2"], "sonic-3",
             note="Voice ids come from the Cartesia library; empty = its default voice."),
    # Language models (router and replies)
    Provider("llm", "anthropic", "Anthropic", ("ANTHROPIC_API_KEY",),
             ["claude-haiku-4-5", "claude-sonnet-4-5", "claude-sonnet-5-5"], "claude-sonnet-4-5", sdk="anthropic"),
    Provider("llm", "openai", "OpenAI", ("OPENAI_API_KEY",), ["gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini"], "gpt-4.1-mini",
             sdk="openai"),
    Provider("llm", "gemini", "Google Gemini", ("GOOGLE_API_KEY", "GEMINI_API_KEY"), ["gemini-3-flash", "gemini-2.5-flash"],
             "gemini-3-flash", sdk="google.generativeai"),
]


def get(component: str, provider_id: str) -> Provider | None:
    return next((p for p in PROVIDERS if p.component == component and p.id == provider_id), None)


def as_dict() -> dict:
    out: dict[str, list[dict]] = {"stt": [], "tts": [], "llm": []}
    for p in PROVIDERS:
        out[p.component].append(p.as_dict())
    # The zero-key placeholder: always there, so a project works before any
    # key is set (routing and tools are real, replies are stand-ins).
    out["llm"].append(
        {
            "component": "llm",
            "id": "fake",
            "label": "No model (placeholder replies)",
            "models": [],
            "default_model": "",
            "voices": [],
            "languages": [],
            "available": True,
            "missing": "",
            "note": "Routing and tools still run for real; replies are scripted stand-ins.",
        }
    )
    return out
