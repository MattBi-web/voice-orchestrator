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
- `FakeProvider` (the zero-API-key default) → a word-overlap heuristic.
  Same honesty rule as `FakeProvider` itself: it exists so the whole
  pipeline (storage, UI, stats) runs with no keys, not as a stand-in for
  judgement. Every heuristic result says in its own rationale exactly what
  it matched, and the result is tagged `method="heuristic"` so the UI can
  label it as such instead of passing it off as an evaluation.
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


@dataclass
class EvaluationCriterion:
    id: str
    name: str
    prompt: str  # what "success" means, in plain language


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
        id="richiesta_risolta",
        name="Richiesta risolta",
        prompt=(
            "L'agente ha risposto alla richiesta del chiamante con un'informazione concreta, "
            "senza bisogno di passarlo a un operatore umano."
        ),
    ),
    EvaluationCriterion(
        id="agente_corretto",
        name="Agente giusto",
        prompt=(
            "La chiamata è finita sull'agente specializzato nell'argomento della richiesta "
            "(per esempio roaming, fatturazione, assistenza tecnica)."
        ),
    ),
]

DEFAULT_DATA_ITEMS = [
    DataCollectionItem(id="motivo_chiamata", type="string", description="Il motivo principale della chiamata, in poche parole."),
    DataCollectionItem(
        id="richiesta_operatore", type="boolean", description="Il chiamante ha chiesto di parlare con un operatore umano."
    ),
]


def format_transcript(turns: list[dict[str, Any]]) -> str:
    lines = []
    for t in turns:
        who = "Chiamante" if t.get("speaker") == "caller" else f"Agente ({t.get('agent_id') or '?'})"
        lines.append(f"{who}: {t.get('text', '')}")
        if t.get("tools"):
            lines.append(f"  [tool usati: {', '.join(t['tools'])}]")
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
            summary="Nessuna trascrizione salvata per questa chiamata (registrata prima che le trascrizioni esistessero).",
            criteria=[CriterionResult(c.id, RESULT_UNKNOWN, "Nessuna trascrizione da valutare.") for c in criteria],
            data=[DataCollectionResult(d.id, None, "Nessuna trascrizione da cui estrarre.") for d in data_items],
        )
    if isinstance(provider, FakeProvider):
        return _heuristic(turns, criteria, data_items)
    try:
        return _llm(turns, criteria, data_items, provider)
    except NotImplementedError:
        return _heuristic(turns, criteria, data_items)


# ---- heuristic (zero API keys) ----


def _words(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower())) - _STOPWORDS


def _heuristic(
    turns: list[dict[str, Any]], criteria: list[EvaluationCriterion], data_items: list[DataCollectionItem]
) -> AnalysisResult:
    full_text = " ".join(t.get("text", "") for t in turns)
    full_words = _words(full_text)
    caller_turns = [t for t in turns if t.get("speaker") == "caller"]

    criteria_results = []
    for c in criteria:
        matched = sorted(_words(c.prompt) & full_words)
        if len(matched) >= 2:
            result = RESULT_SUCCESS
        elif matched:
            result = RESULT_UNKNOWN
        else:
            result = RESULT_FAILURE
        found = ", ".join(matched) if matched else "nessuna"
        criteria_results.append(
            CriterionResult(
                c.id,
                result,
                f"Euristica, non un giudizio: parole del criterio trovate nella trascrizione: {found} "
                "(≥2 = success, 1 = unknown, 0 = failure).",
            )
        )

    data_results = []
    for d in data_items:
        wanted = _words(d.description)
        scored = [(len(wanted & _words(t.get("text", ""))), t) for t in caller_turns]
        best_score, best_turn = max(scored, key=lambda s: s[0]) if scored else (0, None)
        if d.type == "boolean":
            value = best_score > 0
            why = "una frase del chiamante contiene parole della descrizione" if value else "nessuna frase del chiamante corrisponde"
        elif d.type in ("integer", "number"):
            source = best_turn if best_score > 0 else None
            nums = re.findall(r"-?\d+(?:[.,]\d+)?", source.get("text", "")) if source else []
            value = (int(float(nums[0].replace(",", "."))) if d.type == "integer" else float(nums[0].replace(",", "."))) if nums else None
            why = "primo numero nella frase del chiamante più pertinente" if nums else "nessun numero trovato"
        else:
            if best_score > 0:
                value, why = best_turn.get("text", "")[:200], "frase del chiamante più pertinente alla descrizione"
            elif caller_turns:
                value, why = caller_turns[0].get("text", "")[:200], "nessuna corrispondenza: uso la prima frase del chiamante"
            else:
                value, why = None, "nessuna frase del chiamante"
        data_results.append(DataCollectionResult(d.id, value, f"Euristica: {why}."))

    agents = [t.get("agent_id") for t in turns if t.get("speaker") == "agent" and t.get("agent_id")]
    # Only facts here — the "this is a heuristic" caveat is the method tag's
    # job (and the UI's), not something to repeat inside every summary.
    summary = f"{len(caller_turns)} turni del chiamante; agenti coinvolti: {', '.join(dict.fromkeys(agents)) or 'nessuno'}."
    return AnalysisResult(method="heuristic", provider="FakeProvider", summary=summary, criteria=criteria_results, data=data_results)


# ---- real LLM ----

_SYSTEM = (
    "Sei un analista di qualità per un call center. Valuti la trascrizione di una chiamata. "
    "Rispondi SOLO con un oggetto JSON valido, senza testo prima o dopo, con questa forma: "
    '{"summary": "<2 frasi>", '
    '"criteria": [{"id": "<id>", "result": "success|failure|unknown", "rationale": "<1 frase>"}], '
    '"data": [{"id": "<id>", "value": <valore o null>, "rationale": "<1 frase>"}]}. '
    "Usa unknown quando la trascrizione non basta per decidere. Non inventare dati: se un campo non "
    "emerge dalla chiamata, value è null."
)


def _llm(
    turns: list[dict[str, Any]],
    criteria: list[EvaluationCriterion],
    data_items: list[DataCollectionItem],
    provider: LLMProvider,
) -> AnalysisResult:
    crit_block = "\n".join(f'- id "{c.id}" ({c.name}): {c.prompt}' for c in criteria) or "(nessuno)"
    data_block = "\n".join(f'- id "{d.id}" (tipo {d.type}): {d.description}' for d in data_items) or "(nessuno)"
    user = (
        f"Criteri di successo:\n{crit_block}\n\n"
        f"Dati da estrarre:\n{data_block}\n\n"
        f"Trascrizione:\n{format_transcript(turns)}"
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
            summary=f"Analisi LLM fallita: {exc}",
            criteria=[CriterionResult(c.id, RESULT_UNKNOWN, "Analisi fallita.") for c in criteria],
            data=[DataCollectionResult(d.id, None, "Analisi fallita.") for d in data_items],
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
        raise ValueError("nessun oggetto JSON nella risposta del modello")
    data = json.loads(raw[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("la risposta del modello non è un oggetto JSON")
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
