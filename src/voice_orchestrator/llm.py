"""LLM provider abstraction — the same local/cloud-swap pattern used in the
other portfolio projects (meeting-copilot, company-brain). `FakeProvider` is
the default: every CLI command and the whole test suite run against it, with
zero API keys. A real provider (Anthropic, OpenAI, or Gemini — the three the
architecture research compared) is a one-line config change
(`VOICE_ORCH_PROVIDER=anthropic`, plus the matching API key env var).

Three capabilities, deliberately kept separate so each can be swapped or
reasoned about on its own:
  - classify   → the LLM-fallback level of the router (routing/router.py),
                 only called when the two cheap levels couldn't decide.
  - respond    → composes the agent's actual reply to the caller.
  - summarize  → condenses old turns into the rolling summary (memory.py),
                 run off the latency-critical path (see orchestrator.py).
"""
from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod

from . import config
from .agents.registry import AgentSpec
from .state import CallSession, Turn

STAY = "__stay__"  # mirrors routing.router.STAY — kept here too to avoid a circular import

# A minimal stopword list so FakeProvider's word-overlap fallback isn't fooled
# by function words that happen to appear in an agent's description/triggers.
_STOPWORDS = {
    "un", "una", "il", "la", "lo", "gli", "le", "di", "a", "da", "in", "con",
    "su", "per", "tra", "fra", "e", "o", "che", "non", "si", "è", "del", "della",
}


class LLMProvider(ABC):
    @abstractmethod
    def classify(
        self, utterance: str, candidates: list[AgentSpec], current_agent_id: str, session: CallSession
    ) -> str:
        """Returns the id of the best-matching candidate, or STAY if none of
        them genuinely fit and the current agent should keep handling it."""
        ...

    @abstractmethod
    def respond(
        self,
        agent: AgentSpec,
        utterance: str,
        context_summary: str,
        recent_turns: list[Turn],
        tool_notes: list[str],
        temperature: float | None = None,
    ) -> str: ...

    @abstractmethod
    def summarize(self, previous_summary: str, turns: list[Turn]) -> str: ...

    def complete(self, system: str, user: str, max_tokens: int = 800, temperature: float | None = None) -> str:
        """A plain system+user completion — used by `analysis.py` for post-call
        evaluation, which needs free-form JSON rather than one of the three
        call-path capabilities above. Deliberately not abstract: the call path
        never needs it, so a provider that can't do it (FakeProvider) just
        doesn't override it, and `analysis.py` falls back to its heuristic."""
        raise NotImplementedError(f"{type(self).__name__} has no free-form completion")


def _format_turns(turns: list[Turn]) -> str:
    return "\n".join(f"{t.speaker}: {t.text}" for t in turns)


class FakeProvider(LLMProvider):
    """No API key, no network call — deterministic rules. Honest about what
    it is: good enough to exercise the whole pipeline (routing, handoffs,
    tools, memory) end to end, not a stand-in for real conversational quality."""

    def classify(
        self, utterance: str, candidates: list[AgentSpec], current_agent_id: str, session: CallSession
    ) -> str:
        # Whole-word overlap, not substring — "un" is a substring of "funziona"
        # and would otherwise spuriously match almost anything.
        words = set(re.findall(r"\w+", utterance.lower())) - _STOPWORDS
        best_id, best_score = None, 0
        for agent in candidates:
            haystack = " ".join([agent.description, *agent.triggers]).lower()
            haystack_words = set(re.findall(r"\w+", haystack))
            score = len(words & haystack_words)
            if score > best_score:
                best_id, best_score = agent.id, score
        return best_id if best_id is not None else STAY

    def respond(
        self,
        agent: AgentSpec,
        utterance: str,
        context_summary: str,
        recent_turns: list[Turn],
        tool_notes: list[str],
        temperature: float | None = None,
    ) -> str:
        # No real model underneath, so temperature is accepted (same
        # signature as every other provider) but has nothing to act on —
        # FakeProvider is deterministic by design.
        if tool_notes:
            return f"[{agent.name}] " + " ".join(tool_notes)
        return f"[{agent.name}] Ho capito: «hai detto '{utterance.strip()}'» — come posso aiutarti su questo?"

    def summarize(self, previous_summary: str, turns: list[Turn]) -> str:
        gist = " | ".join(f"{t.speaker}: {t.text[:60]}" for t in turns)
        combined = f"{previous_summary} | {gist}" if previous_summary else gist
        return combined[-600:]  # cheap bound so the "summary" doesn't itself grow unbounded


class AnthropicProvider(LLMProvider):
    def __init__(self, model: str = config.ANTHROPIC_MODEL):
        import anthropic

        self._client = anthropic.Anthropic()
        self._model = model

    def _complete(self, system: str, user: str, max_tokens: int = 300, temperature: float | None = None) -> str:
        kwargs = {} if temperature is None else {"temperature": temperature}
        response = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            **kwargs,
        )
        return "".join(b.text for b in response.content if b.type == "text").strip()

    def complete(self, system: str, user: str, max_tokens: int = 800, temperature: float | None = None) -> str:
        return self._complete(system, user, max_tokens=max_tokens, temperature=temperature)

    def classify(
        self, utterance: str, candidates: list[AgentSpec], current_agent_id: str, session: CallSession
    ) -> str:
        options = "\n".join(f"- {a.id}: {a.description}" for a in candidates)
        system = (
            "You are a call-routing classifier. Reply with ONLY one id: either the best-matching "
            f"agent below, or {STAY!r} if none of them genuinely fit and the current agent should "
            "keep handling it. Nothing else in your reply."
        )
        user = f"Agents:\n{options}\n\nCaller said: {utterance!r}\n\nWhich id fits best?"
        reply = self._complete(system, user, max_tokens=20)
        ids = {a.id for a in candidates}
        return reply if reply in ids or reply == STAY else STAY

    def respond(
        self,
        agent: AgentSpec,
        utterance: str,
        context_summary: str,
        recent_turns: list[Turn],
        tool_notes: list[str],
        temperature: float | None = None,
    ) -> str:
        system = agent.system_prompt or f"You are {agent.name}, a helpful phone agent."
        context = f"Conversation so far: {context_summary}\n\n" if context_summary else ""
        context += f"Recent turns:\n{_format_turns(recent_turns)}\n\n" if recent_turns else ""
        if tool_notes:
            context += "Tool results to ground your reply on:\n" + "\n".join(tool_notes) + "\n\n"
        user = f"{context}Caller just said: {utterance!r}\n\nReply as the agent, briefly (voice call, not chat)."
        return self._complete(system, user, temperature=temperature)

    def summarize(self, previous_summary: str, turns: list[Turn]) -> str:
        system = "Condense this call so far into 2-3 short sentences an agent can resume from."
        user = f"Previous summary: {previous_summary}\n\nNew turns:\n{_format_turns(turns)}"
        return self._complete(system, user, max_tokens=150)


class OpenAIProvider(LLMProvider):
    def __init__(self, model: str = config.OPENAI_MODEL):
        from openai import OpenAI

        self._client = OpenAI()
        self._model = model

    def _complete(self, system: str, user: str, max_tokens: int = 300, temperature: float | None = None) -> str:
        kwargs = {} if temperature is None else {"temperature": temperature}
        response = self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            **kwargs,
        )
        return (response.choices[0].message.content or "").strip()

    def complete(self, system: str, user: str, max_tokens: int = 800, temperature: float | None = None) -> str:
        return self._complete(system, user, max_tokens=max_tokens, temperature=temperature)

    def classify(
        self, utterance: str, candidates: list[AgentSpec], current_agent_id: str, session: CallSession
    ) -> str:
        options = "\n".join(f"- {a.id}: {a.description}" for a in candidates)
        reply = self._complete(
            f"Reply with ONLY the best-matching agent id, or {STAY!r} if none genuinely fit.",
            f"Agents:\n{options}\n\nCaller said: {utterance!r}",
            max_tokens=20,
        )
        ids = {a.id for a in candidates}
        return reply if reply in ids or reply == STAY else STAY

    def respond(self, agent, utterance, context_summary, recent_turns, tool_notes, temperature=None) -> str:
        system = agent.system_prompt or f"You are {agent.name}, a helpful phone agent."
        context = f"Conversation so far: {context_summary}\n\n" if context_summary else ""
        if tool_notes:
            context += "Tool results:\n" + "\n".join(tool_notes) + "\n\n"
        return self._complete(system, f"{context}Caller said: {utterance!r}. Reply briefly.", temperature=temperature)

    def summarize(self, previous_summary: str, turns: list[Turn]) -> str:
        return self._complete(
            "Condense into 2-3 short sentences.",
            f"Previous: {previous_summary}\n\nTurns:\n{_format_turns(turns)}",
            max_tokens=150,
        )


class GeminiProvider(LLMProvider):
    def __init__(self, model: str = config.GEMINI_MODEL):
        import google.generativeai as genai

        genai.configure(api_key=os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"))
        self._model = genai.GenerativeModel(model)

    def _complete(self, prompt: str, temperature: float | None = None) -> str:
        import google.generativeai as genai

        kwargs = {} if temperature is None else {"generation_config": genai.GenerationConfig(temperature=temperature)}
        return self._model.generate_content(prompt, **kwargs).text.strip()

    def complete(self, system: str, user: str, max_tokens: int = 800, temperature: float | None = None) -> str:
        return self._complete(f"{system}\n\n{user}", temperature=temperature)

    def classify(
        self, utterance: str, candidates: list[AgentSpec], current_agent_id: str, session: CallSession
    ) -> str:
        options = "\n".join(f"- {a.id}: {a.description}" for a in candidates)
        reply = self._complete(
            f"Reply with ONLY the best agent id, or {STAY!r} if none genuinely fit.\n"
            f"Agents:\n{options}\n\nCaller said: {utterance!r}"
        )
        ids = {a.id for a in candidates}
        return reply if reply in ids or reply == STAY else STAY

    def respond(self, agent, utterance, context_summary, recent_turns, tool_notes, temperature=None) -> str:
        system = agent.system_prompt or f"You are {agent.name}, a helpful phone agent."
        context = f"Conversation so far: {context_summary}\n\n" if context_summary else ""
        if tool_notes:
            context += "Tool results:\n" + "\n".join(tool_notes) + "\n\n"
        return self._complete(
            f"{system}\n\n{context}Caller said: {utterance!r}. Reply briefly.", temperature=temperature
        )

    def summarize(self, previous_summary: str, turns: list[Turn]) -> str:
        return self._complete(f"Condense into 2-3 sentences.\n{previous_summary}\n{_format_turns(turns)}")


def get_provider(name: str | None = None, model: str | None = None) -> LLMProvider:
    name = (name or config.PROVIDER).lower()
    kwargs = {} if not model else {"model": model}
    try:
        if name == "anthropic":
            return AnthropicProvider(**kwargs)
        if name == "openai":
            return OpenAIProvider(**kwargs)
        if name == "gemini":
            return GeminiProvider(**kwargs)
    except Exception:
        return FakeProvider()
    return FakeProvider()


# Per-agent provider instances (blocco 2), cached by (provider name, model):
# AnthropicProvider/OpenAIProvider/GeminiProvider each open a real client in
# __init__, so resolving a fresh one on every single turn would reopen that
# client every time instead of reusing it — same reasoning as any other
# connection pool. Keyed process-wide rather than per-call/per-session
# because the whole point is that two different calls routing into the same
# agent share one client.
_agent_provider_cache: dict[tuple[str, str], LLMProvider] = {}


def get_provider_for_agent(agent: AgentSpec, default: LLMProvider) -> LLMProvider:
    """What orchestrator.py calls to decide which provider composes
    *this* agent's reply. An agent with no `llm_provider` override just
    inherits `default` (the provider the call is already using) — so a
    family where no agent sets this behaves exactly as before blocco 2.
    `get_provider()` itself already falls back to FakeProvider on any
    construction error (missing key, bad model name, network/import
    failure), so a typo'd provider name here degrades the same way a bad
    global VOICE_ORCH_PROVIDER would, not with an unhandled exception
    mid-call."""
    if not agent.llm_provider:
        return default
    key = (agent.llm_provider.lower(), agent.llm_model or "")
    cached = _agent_provider_cache.get(key)
    if cached is not None:
        return cached
    provider = get_provider(agent.llm_provider, model=agent.llm_model or None)
    _agent_provider_cache[key] = provider
    return provider
