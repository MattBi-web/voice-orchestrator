import pytest

from voice_orchestrator import config
from voice_orchestrator.agents.registry import AgentSpec, add_agent, load_family, remove_agent
from voice_orchestrator.eval_data import EVAL_SET
from voice_orchestrator.llm import FakeProvider
from voice_orchestrator.orchestrator import handle_turn
from voice_orchestrator.routing.gate import UnsafeExpression, is_eligible
from voice_orchestrator.routing.router import route
from voice_orchestrator.state import CallSession


@pytest.fixture(scope="module")
def root():
    return load_family(config.AGENTS_FILE)


@pytest.fixture()
def provider():
    return FakeProvider()


def _route(root, start_id, utterance, slots, provider):
    current = root.find(start_id)
    session = CallSession(call_id="test")
    session.slots.update(slots)
    decision = route(
        utterance,
        current,
        session,
        llm_fallback=lambda u, candidates, cur_id, s: provider.classify(u, candidates, cur_id, s),
    )
    return decision, session


def test_family_loads_with_expected_shape(root):
    ids = {a.id for a in root.iter_subtree()}
    assert {"router", "billing", "sales", "tech_support", "tech_internet", "tech_tv"} <= ids


@pytest.mark.parametrize("start_id,utterance,expected,slots", EVAL_SET)
def test_routing_eval_set(root, provider, start_id, utterance, expected, slots):
    decision, _ = _route(root, start_id, utterance, slots, provider)
    assert decision.chosen_agent_id == expected


def test_hit_rate_is_high(root, provider):
    hits = sum(
        1
        for start_id, utterance, expected, slots in EVAL_SET
        if _route(root, start_id, utterance, slots, provider)[0].chosen_agent_id == expected
    )
    assert hits / len(EVAL_SET) >= 0.85


def test_most_decisions_avoid_the_llm_fallback(root, provider):
    """The whole point of the two-level design: most routing should resolve
    at gate_only/pattern, not llm_fallback."""
    levels = [
        _route(root, start_id, utterance, slots, provider)[0].resolved_by
        for start_id, utterance, expected, slots in EVAL_SET
    ]
    cheap = sum(1 for lvl in levels if lvl in ("gate_only", "pattern"))
    assert cheap / len(levels) >= 0.6


def test_gate_blocks_billing_when_not_authenticated(root, provider):
    decision, _ = _route(root, "router", "quanto devo pagare?", {"authenticated": False}, provider)
    assert "billing" not in decision.eligible_agents
    assert decision.chosen_agent_id == "router"


def test_gate_expression_rejects_unsafe_input():
    with pytest.raises(UnsafeExpression):
        is_eligible("__import__('os').system('echo pwned')", {})


def test_full_turn_handoff_and_tool_trigger(root, provider):
    session = CallSession(call_id="test-turn")
    session.slots["authenticated"] = True
    result = handle_turn(session, root, "quanto devo pagare questo mese?", provider)
    assert result.agent.id == "billing"
    assert result.handed_off is True
    assert "check_account_status" in result.tool_ids_used


def test_nested_handoff_two_hops(root, provider):
    session = CallSession(call_id="test-nested")
    r1 = handle_turn(session, root, "il wifi non si connette", provider)
    assert r1.agent.id == "tech_support"
    r2 = handle_turn(session, root, "il router ha la luce rossa", provider)
    assert r2.agent.id == "tech_internet"


def test_transfer_tool_sets_session_flag(root, provider):
    session = CallSession(call_id="test-transfer")
    result = handle_turn(session, root, "voglio parlare con un operatore", provider)
    assert session.slots.get("transferred") is True
    assert "transfer_to_human" in result.tool_ids_used


def test_add_and_remove_agent_roundtrip(root):
    new_agent = AgentSpec(id="roaming", name="Roaming Support", description="Handles roaming questions")
    add_agent(root, "tech_support", new_agent)
    assert root.find("roaming") is not None
    removed = remove_agent(root, "roaming")
    assert removed.id == "roaming"
    assert root.find("roaming") is None
