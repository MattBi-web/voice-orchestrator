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


def test_tool_condition_gates_on_channel(root, provider):
    """check_account_status is configured with condition: channel == 'voice'
    (config/agents.yaml) — on a 'chat' channel it must not fire, even though
    the same utterance triggers it on 'voice' (test_full_turn_handoff_and_tool_trigger)."""
    session = CallSession(call_id="test-channel", channel="chat")
    session.slots["authenticated"] = True
    result = handle_turn(session, root, "quanto devo pagare questo mese?", provider)
    assert result.agent.id == "billing"
    assert "check_account_status" not in result.tool_ids_used
    assert "knowledge_lookup" in result.tool_ids_used  # no condition on this one — still fires


def test_structured_events_recorded_for_routing_handoff_and_tools(root, provider):
    """Every routing decision, handoff, and tool outcome (triggered or
    skipped by a condition) should also land in the generic event_log, not
    just the specific routing_log/handoff_log/tool_ids_used."""
    session = CallSession(call_id="test-events", channel="chat")  # chat -> check_account_status is condition-gated off
    session.slots["authenticated"] = True
    handle_turn(session, root, "quanto devo pagare questo mese?", provider)

    counts = session.event_counts()
    assert counts.get("router.routing_decision", 0) >= 1
    assert counts.get("agent.handoff", 0) == 1  # router -> billing
    assert counts.get("tool.tool_triggered", 0) >= 1  # knowledge_lookup (no condition)
    assert counts.get("tool.tool_skipped_condition", 0) == 1  # check_account_status, blocked by channel == 'voice'


def test_add_and_remove_agent_roundtrip(root):
    new_agent = AgentSpec(id="scratch_test_agent", name="Scratch Agent", description="Throwaway test agent")
    add_agent(root, "tech_support", new_agent)
    assert root.find("scratch_test_agent") is not None
    removed = remove_agent(root, "scratch_test_agent")
    assert removed.id == "scratch_test_agent"
    assert root.find("scratch_test_agent") is None
