"""Hand-labeled routing cases: (start_agent_id, utterance, expected_agent_id,
slots). Each is a single routing decision (not a full conversation), which is
enough to check that the gate, the keyword classifier, and the LLM fallback
each do their job — and, via `voice-orchestrator eval`'s level breakdown, to
show how few decisions actually need the expensive fallback level.
"""

EVAL_SET: list[tuple[str, str, str, dict]] = [
    # Level 2 (keyword classifier) should resolve these without any model call.
    ("router", "quanto devo pagare questo mese?", "billing", {"authenticated": True}),
    ("router", "vorrei fare l'upgrade al piano Max", "sales", {}),
    ("router", "il wifi non si connette da ieri", "tech_support", {}),
    ("tech_support", "il router ha la luce rossa", "tech_internet", {}),
    ("tech_support", "il decoder non si accende più", "tech_tv", {}),
    ("tech_support", "non vedo più alcuni canali dopo l'upgrade", "tech_tv", {}),

    # Level 1 (gate): billing isn't even eligible when not authenticated — the
    # router should stay put rather than transfer, regardless of the classifier.
    ("router", "quanto devo pagare questo mese?", "router", {"authenticated": False}),

    # Ambiguous / no keyword match at all: should fall through to the LLM
    # fallback level (FakeProvider.classify) and, since nothing genuinely
    # fits, land on STAY — i.e. stay at the router.
    ("router", "buongiorno, volevo solo un'informazione generale", "router", {}),
]
