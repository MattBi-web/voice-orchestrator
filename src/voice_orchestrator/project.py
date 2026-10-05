"""Projects and their model settings (blocco 8).

A project is one phone line: a single agent, or a workflow where a
receptionist hands the call to specialists. It carries the default models
for every piece of the pipeline:

    STT (speech to text) -> router (gate, pattern, then an LLM) ->
    the answering agent's LLM -> tools -> TTS (text to speech)

Every agent inherits the project's choice and can override any of it, field
by field. An empty field always means "inherit". One rule keeps overrides
coherent: an agent that switches *provider* (say TTS from ElevenLabs to
OpenAI) does not inherit the project's model or voice, because those
belong to the other provider; it gets its own or the provider's default.

Plain dataclasses, no web or livekit import, so the CLI, the web API, the
voice worker and the tests resolve a pipeline the same way.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, fields

from . import config
from .agents.registry import AgentSpec
from .llm import FakeProvider, LLMProvider, cached_provider

DEFAULT_PROJECT = "demo"


@dataclass
class ModelSettings:
    stt_provider: str = "deepgram"
    stt_model: str = "nova-3"
    stt_language: str = "multi"
    tts_provider: str = "elevenlabs"
    tts_model: str = "eleven_flash_v2_5"
    voice_id: str = ""
    voice_stability: float | None = None
    voice_speed: float | None = None
    # "" = the deployment's VOICE_ORCH_PROVIDER (fake unless configured).
    llm_provider: str = ""
    llm_model: str = ""
    llm_temperature: float | None = None
    # "" = same provider/model as llm_*. The router's LLM only runs when the
    # gate and the keywords can't settle a turn, so a small fast model is
    # the usual choice here.
    router_provider: str = ""
    router_model: str = ""

    @classmethod
    def from_dict(cls, data: dict | None) -> "ModelSettings":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (data or {}).items() if k in known})

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Choice:
    """One resolved pipeline component. `source` says where the provider
    came from: "agent" (this agent overrides it), "project" (inherited), or
    "deployment" (nothing chosen: the server's VOICE_ORCH_PROVIDER)."""

    component: str
    provider: str
    model: str
    source: str
    extra: dict

    def as_dict(self) -> dict:
        return {"component": self.component, "provider": self.provider, "model": self.model, "source": self.source, **self.extra}


def _pick(agent_provider: str, agent_values: dict, project_provider: str, project_values: dict) -> tuple[str, dict, str]:
    """Field-wise inheritance with the provider-switch rule (module doc)."""
    if agent_provider and agent_provider != project_provider:
        return agent_provider, {k: v for k, v in agent_values.items()}, "agent"
    merged = {k: (agent_values[k] if agent_values[k] not in ("", None) else project_values.get(k)) for k in agent_values}
    overridden = bool(agent_provider) or any(agent_values[k] not in ("", None) for k in agent_values)
    return project_provider, merged, "agent" if overridden else "project"


def stt_for(agent: AgentSpec, s: ModelSettings) -> Choice:
    provider, v, source = _pick(
        agent.stt_provider,
        {"model": agent.stt_model, "language": agent.stt_language},
        s.stt_provider,
        {"model": s.stt_model, "language": s.stt_language},
    )
    return Choice("stt", provider, v["model"] or "", source, {"language": v["language"] or ""})


def tts_for(agent: AgentSpec, s: ModelSettings) -> Choice:
    provider, v, source = _pick(
        agent.tts_provider,
        {"model": agent.tts_model, "voice_id": agent.voice_id, "stability": agent.voice_stability, "speed": agent.voice_speed},
        s.tts_provider,
        {"model": s.tts_model, "voice_id": s.voice_id, "stability": s.voice_stability, "speed": s.voice_speed},
    )
    return Choice(
        "tts", provider, v["model"] or "", source, {"voice_id": v["voice_id"] or "", "stability": v["stability"], "speed": v["speed"]}
    )


def llm_for(agent: AgentSpec, s: ModelSettings) -> Choice:
    provider, v, source = _pick(
        agent.llm_provider,
        {"model": agent.llm_model, "temperature": agent.llm_temperature},
        s.llm_provider,
        {"model": s.llm_model, "temperature": s.llm_temperature},
    )
    if not provider:
        provider, source = config.PROVIDER, "deployment"
    return Choice("llm", provider, v["model"] or "", source, {"temperature": v["temperature"]})


def router_for(s: ModelSettings) -> Choice:
    if s.router_provider:
        return Choice("router", s.router_provider, s.router_model, "project", {})
    if s.llm_provider:
        return Choice("router", s.llm_provider, s.router_model or s.llm_model, "project", {})
    return Choice("router", config.PROVIDER, s.router_model or s.llm_model, "deployment", {})


@dataclass
class Project:
    id: str
    name: str
    description: str = ""
    settings: ModelSettings = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.settings is None:
            self.settings = ModelSettings()


def slugify(name: str) -> str:
    """Project ids are slugs: lowercase letters, digits, single dashes. The
    voice room name uses "--" as a separator, so it can't appear in one."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)[:40] or "agent"


def router_provider(s: ModelSettings, force_fake: bool = False) -> LLMProvider:
    """The provider the router's LLM level (and the history summary) uses."""
    if force_fake:
        return FakeProvider()
    c = router_for(s)
    return cached_provider(c.provider, c.model)


def responder(s: ModelSettings, force_fake: bool = False):
    """For orchestrator.handle_turn(responder=...): agent -> (provider,
    temperature), the project default or the agent's override."""

    def pick(agent: AgentSpec) -> tuple[LLMProvider, float | None]:
        if force_fake:
            return FakeProvider(), None
        c = llm_for(agent, s)
        return cached_provider(c.provider, c.model), c.extra["temperature"]

    return pick


def pipeline(agent: AgentSpec, s: ModelSettings) -> list[dict]:
    """The agent's pipeline in call order, each piece with the model it
    will actually use and whether that comes from the agent or the project.
    What the UI's Pipeline view and the Developer tab show."""
    return [stt_for(agent, s).as_dict(), router_for(s).as_dict(), llm_for(agent, s).as_dict(), tts_for(agent, s).as_dict()]
