"""load_family/save_family round-trip — not covered directly anywhere before
(cli.py's `agents add`/`agents remove` exercise save_family only indirectly,
and the web API's new POST /api/agents/export is about to become a third
caller of it). Worth pinning down on its own, since a round-trip bug here
would now surface as a silently wrong agents.yaml rather than just a test
failure.
"""
from __future__ import annotations

from voice_orchestrator.agents.registry import AgentSpec, ToolBinding, load_family, save_family


def _family() -> AgentSpec:
    return AgentSpec(
        id="router",
        name="Router",
        description="Routes calls",
        system_prompt="You are the router.",
        eligibility="",
        triggers=[],
        tools=[],
        knowledge=[],
        voice="default",
        children=[
            AgentSpec(
                id="billing",
                name="Billing",
                description="Handles billing",
                system_prompt="You handle billing.",
                eligibility="authenticated == true",
                triggers=["bolletta", "fattura"],
                tools=[ToolBinding(id="knowledge_lookup"), ToolBinding(id="transfer_to_human", condition="channel == 'voice'")],
                knowledge=["billing.md"],
                voice="it-female-1",
                children=[],
            ),
        ],
    )


def test_save_then_load_round_trips_every_field(tmp_path):
    path = tmp_path / "agents.yaml"
    original = _family()

    save_family(original, path)
    loaded = load_family(path)

    assert loaded == original


def test_save_omits_default_valued_fields_for_a_clean_diff(tmp_path):
    """save_family only writes eligibility/triggers/tools/knowledge/voice
    when they differ from the empty/default value — so a plain agent stays a
    short, readable YAML block instead of every optional key spelled out."""
    path = tmp_path / "agents.yaml"
    plain = AgentSpec(id="router", name="Router", description="d", system_prompt="s")

    save_family(plain, path)
    text = path.read_text(encoding="utf-8")

    assert "eligibility" not in text
    assert "triggers" not in text
    assert "tools" not in text
    assert "knowledge" not in text
    assert "voice" not in text


def test_save_overwrites_an_existing_file(tmp_path):
    path = tmp_path / "agents.yaml"
    save_family(_family(), path)
    smaller = AgentSpec(id="router", name="Router", description="d", system_prompt="s")

    save_family(smaller, path)
    loaded = load_family(path)

    assert loaded.children == []
