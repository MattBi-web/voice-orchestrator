"""Level 2 of the router: a lightweight, fast classifier over the agents the
gate already deemed eligible. This is the "Calpurnia-style" dedicated router
— deliberately NOT the conversational LLM, so the common case resolves in
microseconds instead of waiting on a generation turn.

Matching is deliberately simple (keyword/phrase scoring): the point of this
layer is to catch the easy, common-case utterances cheaply. Anything it
can't resolve confidently falls through to the LLM fallback in router.py —
this file's whole value is in knowing when to give up, not in being clever.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..agents.registry import AgentSpec

# A match needs to beat the runner-up by at least this many points to count as
# unambiguous — otherwise two agents are too close to call without the LLM.
MIN_MARGIN = 1


@dataclass
class ClassifierResult:
    agent_id: str | None  # None means "ambiguous, fall through to the LLM"
    scores: dict[str, int]


def _score(utterance: str, agent: AgentSpec) -> int:
    text = utterance.lower()
    score = 0
    for trigger in agent.triggers:
        # Leading word-boundary, but deliberately no trailing one: triggers are
        # written as short stems (e.g. "pag", "canal") so one entry catches
        # Italian verb/plural inflections (pagare/pago/pagamento, canale/canali)
        # without needing a real stemmer for a config this size.
        pattern = r"(?<!\w)" + re.escape(trigger.lower())
        score += len(re.findall(pattern, text))
    return score


def classify(utterance: str, eligible_agents: list[AgentSpec]) -> ClassifierResult:
    scored = {agent.id: _score(utterance, agent) for agent in eligible_agents}
    ranked = sorted(scored.items(), key=lambda kv: -kv[1])

    if not ranked or ranked[0][1] == 0:
        return ClassifierResult(agent_id=None, scores=scored)

    top_id, top_score = ranked[0]
    runner_up_score = ranked[1][1] if len(ranked) > 1 else -1

    if top_score - runner_up_score >= MIN_MARGIN:
        return ClassifierResult(agent_id=top_id, scores=scored)
    return ClassifierResult(agent_id=None, scores=scored)
