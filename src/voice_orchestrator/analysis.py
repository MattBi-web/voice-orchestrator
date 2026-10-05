"""Post-call analysis — the equivalent of ElevenLabs' `evaluation.criteria` +
`data_collection`: judge a finished call against a set of success criteria,
and extract a few typed fields from it (reason for the call, whether the
caller asked for a human, ...).

Core module, standard library only (same rule as `call_log.py`): it takes a
transcript (the `turns` list `call_log` already writes) plus the criteria
and data items, and returns an `AnalysisResult`. Where the criteria are
stored and where results are kept is the web API's business (SQLite, see
`webapi/models.py`), not this module's.

Two ways to judge, chosen by the provider:

- a real LLM provider (Anthropic/OpenAI/Gemini) → one LLM call asked for
  strict JSON, parsed defensively;
- `FakeProvider` (the zero-API-key default) → no judgement at all for
  criteria written in natural language: they come back `unknown`, saying a
  provider is needed. (They used to get a word-overlap score, which gave
  confident nonsense such as "Agente giusto: fallito" on a correct routing —
  D11.) Data items still get a word-overlap guess, tagged as such.

Independent of the provider, a criterion can be *structural* (`kind`): a
fact the transcript records exactly — where the call ended up, which tools
ran. Those are checked deterministically in both modes, never sent to an
LLM, so they're the criteria that stay meaningful with zero API keys.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .llm import FakeProvider, LLMProvider

RESULT_SUCCESS = "success"
RESULT_FAILURE = "failure"
RESULT_UNKNOWN = "unknown"
_RESULTS = {RESULT_SUCCESS, RESULT_FAILURE, RESULT_UNKNOWN}

DATA_TYPES = ("string", "boolean", "integer", "number")

_STOPWORDS = {
    "un", "una", "uno", "il", "la", "lo", "i", "gli", "le", "l", "di", "a", "da", "in", "con",
    "su", "per", "tra", "fra", "e", "o", "che", "non", "si", "è", "del", "della", "dello", "dei",
    "delle", "al", "alla", "allo", "ai", "alle", "nel", "nella", "ha", "ho", "hai", "sono", "come",
    "senza", "suo", "sua", "più", "poche", "parole", "esempio", "per", "se", "ma", "anche", "the",
    "a", "an", "of", "to", "and", "or", "is", "was",
}


# Criterion kinds (D11). KIND_LLM is judged by a model from `prompt`; the
# others are checked against the transcript's own structure, with `expected`
# as their argument.
KIND_LLM = "llm"
KIND_FINAL_AGENT = "final_agent"  # call ended on one of `expected` (empty: anywhere but the entry agent)
KIND_TOOL_USED = "tool_used"  # at least one of `expected` ran
KIND_TOOL_NOT_USED = "tool_not_used"  # none of `expected` ran
KINDS = (KIND_LLM, KIND_FINAL_AGENT, KIND_TOOL_USED, KIND_TOOL_NOT_USED)


@dataclass
class EvaluationCriterion:
    id: str
    name: str
    prompt: str  # what "success" means, in plain language
    kind: str = KIND_LLM
    expected: list[str] = field(default_factory=list)


@dataclass
class DataCollectionItem:
    id: str
    type: str  # one of DATA_TYPES
    description: str  # what to extract, in plain language


@dataclass
class CriterionResult:
    criterion_id: str
    result: str  # RESULT_SUCCESS | RESULT_FAILURE | RESULT_UNKNOWN
    rationale: str


@dataclass
class DataCollectionResult:
    item_id: str
    value: Any  # None when not found
    rationale: str


@dataclass
class AnalysisResult:
    method: str  # "heuristic" | "llm"
    provider: str
    summary: str
    criteria: list[CriterionResult] = field(default_factory=list)
    data: list[DataCollectionResult] = field(default_factory=list)

    @property
    def call_successful(self) -> str:
        """The single verdict the dashboard aggregates: success only if every
        criterion succeeded, failure if any failed, unknown otherwise (or if
        there are no criteria at all)."""
        results = [c.result for c in self.criteria]
        if not results:
            return RESULT_UNKNOWN
        if RESULT_FAILURE in results:
            return RESULT_FAILURE
        if all(r == RESULT_SUCCESS for r in results):
            return RESULT_SUCCESS
        return RESULT_UNKNOWN

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["call_successful"] = self.call_successful
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnalysisResult":
        return cls(
            method=data.get("method", "heuristic"),
            provider=data.get("provider", ""),
            summary=data.get("summary", ""),
            criteria=[CriterionResult(**c) for c in data.get("criteria", [])],
            data=[DataCollectionResult(**d) for d in data.get("data", [])],
        )


# Seeded once into the web API's database (webapi/seed.py), then editable
# from the UI. Written for the bundled Meridian Telecom demo family.
DEFAULT_CRITERIA = [
    EvaluationCriterion(
        id="request_resolved",
        name="Request resolved",
        prompt=(
            "The agent answered the caller's request with concrete information, "
            "without needing to hand the call to a human."
        ),
    ),
    EvaluationCriterion(
        id="reached_specialist",
        name="Reached a specialist",
        prompt="The call moved from the receptionist to a specialist agent.",
        kind=KIND_FINAL_AGENT,
    ),
    EvaluationCriterion(
        id="no_human_handover",
        name="No human handover",
        prompt="The call ended without being handed to a human.",
        kind=KIND_TOOL_NOT_USED,
        expected=["transfer_to_human"],
    ),
]

DEFAULT_DATA_ITEMS = [
    DataCollectionItem(id="call_reason", type="string", description="The main reason for the call, in a few words."),
    # The demo agents speak Italian: the Italian words are in the description
    # so the keyless word-overlap fallback can still match a real request.
    DataCollectionItem(
        id="asked_for_human",
        type="boolean",
        description="The caller asked to speak to a human (in Italian: operatore, persona vera).",
    ),
]


def format_transcript(turns: list[dict[str, Any]]) -> str:
    lines = []
    for t in turns:
        who = "Caller" if t.get("speaker") == "caller" else f"Agent ({t.get('agent_id') or '?'})"
        lines.append(f"{who}: {t.get('text', '')}")
        if t.get("tools"):
            lines.append(f"  [tools used: {', '.join(t['tools'])}]")
    return "\n".join(lines)


def analyze(
    turns: list[dict[str, Any]],
    criteria: list[EvaluationCriterion],
    data_items: list[DataCollectionItem],
    provider: LLMProvider,
) -> AnalysisResult:
    if not turns:
        return AnalysisResult(
            method="heuristic" if isinstance(provider, FakeProvider) else "llm",
            provider=type(provider).__name__,
            summary="No transcript was saved for this call (recorded before transcripts existed).",
            criteria=[CriterionResult(c.id, RESULT_UNKNOWN, "No transcript to evaluate.") for c in criteria],
            data=[DataCollectionResult(d.id, None, "No transcript to extract from.") for d in data_items],
        )
    if isinstance(provider, FakeProvider):
        result = _heuristic(turns, criteria, data_items)
    else:
        try:
            result = _llm(turns, [c for c in criteria if c.kind == KIND_LLM], data_items, provider)
        except NotImplementedError:
            result = _heuristic(turns, criteria, data_items)
    # Structural criteria are checked here, the same way whatever the
    # provider, and slotted back into the configured order.
    by_id = {r.criterion_id: r for r in result.criteria}
    result.criteria = [
        by_id[c.id] if c.kind == KIND_LLM else _structural(turns, c) for c in criteria
    ]
    return result


# ---- structural (deterministic, any provider) ----


def _structural(turns: list[dict[str, Any]], c: EvaluationCriterion) -> CriterionResult:
    agent_ids = [t.get("agent_id") for t in turns if t.get("speaker") == "agent" and t.get("agent_id")]
    used = {tool for t in turns for tool in (t.get("tools") or [])}
    expected = [e for e in c.expected if e]
    prefix = "Fact check: "

    if c.kind == KIND_FINAL_AGENT:
        if not agent_ids:
            return CriterionResult(c.id, RESULT_UNKNOWN, prefix + "no agent reply in the transcript.")
        final = agent_ids[-1]
        if expected:
            ok = final in expected
            return CriterionResult(
                c.id,
                RESULT_SUCCESS if ok else RESULT_FAILURE,
                prefix + f"call ended with {final!r}, expected {', '.join(expected)}.",
            )
        entry = agent_ids[0]
        ok = final != entry
        why = f"moved from {entry!r} to {final!r}." if ok else f"stayed with the first agent, {entry!r}."
        return CriterionResult(c.id, RESULT_SUCCESS if ok else RESULT_FAILURE, prefix + "call " + why)

    if c.kind in (KIND_TOOL_USED, KIND_TOOL_NOT_USED):
        hit = sorted(used & set(expected))
        found = ", ".join(hit) if hit else "nessuno"
        if c.kind == KIND_TOOL_USED:
            ok = bool(hit)
        else:
            ok = not hit
        return CriterionResult(
            c.id,
            RESULT_SUCCESS if ok else RESULT_FAILURE,
            prefix + f"tool {', '.join(expected)} — usati in questa chiamata: {found}.",
        )

    return CriterionResult(c.id, RESULT_UNKNOWN, f"Unknown criterion kind: {c.kind!r}.")


# ---- heuristic (zero API keys) ----


def _words(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower())) - _STOPWORDS


def _heuristic(
    turns: list[dict[str, Any]], criteria: list[EvaluationCriterion], data_items: list[DataCollectionItem]
) -> AnalysisResult:
    caller_turns = [t for t in turns if t.get("speaker") == "caller"]

    # D11: a natural-language criterion needs a model to judge it. Without
    # one, "unknown" is the only honest answer — any word-overlap score here
    # reads as a verdict and is wrong as often as it's right.
    criteria_results = [
        CriterionResult(
            c.id,
            RESULT_UNKNOWN,
            "Not evaluated: a criterion written in plain language needs a language model "
            "(VOICE_ORCH_PROVIDER). Without one, only fact-check criteria get a verdict.",
        )
        for c in criteria
    ]

    data_results = []
    for d in data_items:
        wanted = _words(d.description)
        scored = [(len(wanted & _words(t.get("text", ""))), t) for t in caller_turns]
        best_score, best_turn = max(scored, key=lambda s: s[0]) if scored else (0, None)
        if d.type == "boolean":
            value = best_score > 0
            why = "a caller sentence shares words with the description" if value else "no caller sentence matches"
        elif d.type in ("integer", "number"):
            source = best_turn if best_score > 0 else None
            nums = re.findall(r"-?\d+(?:[.,]\d+)?", source.get("text", "")) if source else []
            value = (int(float(nums[0].replace(",", "."))) if d.type == "integer" else float(nums[0].replace(",", "."))) if nums else None
            why = "first number in the closest caller sentence" if nums else "no number found"
        else:
            if best_score > 0:
                value, why = best_turn.get("text", "")[:200], "caller sentence closest to the description"
            elif caller_turns:
                value, why = caller_turns[0].get("text", "")[:200], "no match: using the first caller sentence"
            else:
                value, why = None, "no caller sentence"
        data_results.append(DataCollectionResult(d.id, value, f"Keyword match: {why}."))

    agents = [t.get("agent_id") for t in turns if t.get("speaker") == "agent" and t.get("agent_id")]
    # Only facts here — the "this is a heuristic" caveat is the method tag's
    # job (and the UI's), not something to repeat inside every summary.
    summary = f"{len(caller_turns)} caller turns; agents involved: {', '.join(dict.fromkeys(agents)) or 'none'}."
    return AnalysisResult(method="heuristic", provider="FakeProvider", summary=summary, criteria=criteria_results, data=data_results)


# ---- real LLM ----

_SYSTEM = (
    "You are a call-center quality analyst evaluating a call transcript (the call itself may be in "
    "Italian; write your answer in English). Reply with ONLY a valid JSON object, no text before or "
    'after, shaped like: {"summary": "<2 sentences>", '
    '"criteria": [{"id": "<id>", "result": "success|failure|unknown", "rationale": "<1 sentence>"}], '
    '"data": [{"id": "<id>", "value": <value or null>, "rationale": "<1 sentence>"}]}. '
    "Use unknown when the transcript isn't enough to decide. Don't invent data: if a field doesn't "
    "come up in the call, its value is null."
)


def _llm(
    turns: list[dict[str, Any]],
    criteria: list[EvaluationCriterion],
    data_items: list[DataCollectionItem],
    provider: LLMProvider,
) -> AnalysisResult:
    crit_block = "\n".join(f'- id "{c.id}" ({c.name}): {c.prompt}' for c in criteria) or "(none)"
    data_block = "\n".join(f'- id "{d.id}" (type {d.type}): {d.description}' for d in data_items) or "(none)"
    user = (
        f"Success criteria:\n{crit_block}\n\n"
        f"Data to extract:\n{data_block}\n\n"
        f"Transcript:\n{format_transcript(turns)}"
    )
    name = type(provider).__name__
    try:
        raw = provider.complete(_SYSTEM, user, max_tokens=900)
        parsed = _parse_json_object(raw)
    except NotImplementedError:
        raise
    except Exception as exc:  # network error, bad JSON, ... — say so, don't fall back silently
        return AnalysisResult(
            method="llm",
            provider=name,
            summary=f"Model evaluation failed: {exc}",
            criteria=[CriterionResult(c.id, RESULT_UNKNOWN, "Evaluation failed.") for c in criteria],
            data=[DataCollectionResult(d.id, None, "Evaluation failed.") for d in data_items],
        )

    by_crit = {str(c.get("id")): c for c in parsed.get("criteria", []) if isinstance(c, dict)}
    by_data = {str(d.get("id")): d for d in parsed.get("data", []) if isinstance(d, dict)}
    criteria_results = []
    for c in criteria:
        got = by_crit.get(c.id, {})
        result = str(got.get("result", RESULT_UNKNOWN)).lower()
        criteria_results.append(
            CriterionResult(c.id, result if result in _RESULTS else RESULT_UNKNOWN, str(got.get("rationale", "Non valutato.")))
        )
    data_results = [
        DataCollectionResult(d.id, _coerce(by_data.get(d.id, {}).get("value"), d.type), str(by_data.get(d.id, {}).get("rationale", "")))
        for d in data_items
    ]
    return AnalysisResult(method="llm", provider=name, summary=str(parsed.get("summary", "")), criteria=criteria_results, data=data_results)


def _parse_json_object(raw: str) -> dict[str, Any]:
    """Models sometimes wrap JSON in ```json fences or a sentence despite
    being told not to — take the outermost {...} span rather than trusting
    the whole reply to be pure JSON."""
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in the model's reply")
    data = json.loads(raw[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("the model's reply is not a JSON object")
    return data


def _coerce(value: Any, type_: str) -> Any:
    if value is None:
        return None
    try:
        if type_ == "boolean":
            if isinstance(value, str):
                return value.strip().lower() in ("true", "sì", "si", "yes", "1")
            return bool(value)
        if type_ == "integer":
            return int(float(value))
        if type_ == "number":
            return float(value)
        return str(value)
    except (TypeError, ValueError):
        return None
