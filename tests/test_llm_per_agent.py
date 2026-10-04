"""Blocco 2 — per-agent LLM override. get_provider_for_agent() in isolation,
plus an end-to-end check through handle_turn() that an agent with no
override still uses the call's own default provider (so a family where no
agent sets llm_provider behaves exactly as before blocco 2), while one that
sets llm_provider="fake" gets a provider the default was never called for.
"""
from __future__ import annotations

from voice_orchestrator.agents.registry import AgentSpec
from voice_orchestrator.llm import FakeProvider, get_provider_for_agent
from voice_orchestrator.orchestrator import handle_turn
from voice_orchestrator.state import CallSession


class _SpyProvider(FakeProvider):
    """A FakeProvider that counts how many times each capability was
    actually invoked, so a test can assert "this provider, not that one,
    answered" without needing a real network-backed provider."""

    def __init__(self):
        self.respond_calls = 0

    def respond(self, *args, **kwargs):
        self.respond_calls += 1
        return super().respond(*args, **kwargs)


def _plain_agent(agent_id="plain") -> AgentSpec:
    return AgentSpec(id=agent_id, name="Plain", description="no override")


def test_get_provider_for_agent_falls_back_to_default_when_unset():
    default = FakeProvider()
    agent = _plain_agent()

    assert get_provider_for_agent(agent, default=default) is default


def test_get_provider_for_agent_resolves_and_caches_an_override():
    default = FakeProvider()
    agent = AgentSpec(id="billing", name="Billing", description="d", llm_provider="fake")

    resolved = get_provider_for_agent(agent, default=default)

    assert resolved is not default
    assert isinstance(resolved, FakeProvider)
    # Same (provider, model) key -> same cached instance, not a fresh one
    # rebuilt on every turn.
    assert get_provider_for_agent(agent, default=default) is resolved


def test_handle_turn_uses_the_default_provider_when_the_agent_has_no_override():
    spy = _SpyProvider()
    root = AgentSpec(id="router", name="Router", description="d")
    session = CallSession(call_id="t1")

    handle_turn(session, root, "ciao", spy)

    assert spy.respond_calls == 1


def test_handle_turn_uses_the_agents_own_provider_when_overridden():
    spy = _SpyProvider()
    root = AgentSpec(id="router", name="Router", description="d", llm_provider="fake", llm_temperature=0.1)
    session = CallSession(call_id="t2")

    result = handle_turn(session, root, "ciao", spy)

    # The spy (passed in as the call's default) was never asked to
    # respond — the router agent's own llm_provider="fake" override
    # resolved to a *different* FakeProvider instance via
    # get_provider_for_agent(), which is the one that actually answered.
    assert spy.respond_calls == 0
    assert result.reply  # the other instance still produced a real reply


def test_fake_provider_accepts_a_temperature_kwarg_without_using_it():
    """Every LLMProvider.respond() now takes `temperature` (blocco 2), even
    FakeProvider, which has nothing to do with it — it just shouldn't
    raise, so callers don't need to special-case "except with FakeProvider"."""
    agent = _plain_agent()
    reply = FakeProvider().respond(
        agent=agent, utterance="ciao", context_summary="", recent_turns=[], tool_notes=[], temperature=0.9
    )
    assert reply
