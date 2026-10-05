"""Tests for analysis.py — post-call evaluation. Core-only (no webapi
import), same as test_call_log.py. The LLM path is exercised with a stub
provider that returns canned text, so nothing here needs an API key."""
from __future__ import annotations

from voice_orchestrator import analysis
from voice_orchestrator.analysis import (
    AnalysisResult,
    CriterionResult,
    DataCollectionItem,
    EvaluationCriterion,
    analyze,
)
from voice_orchestrator.llm import FakeProvider, LLMProvider

TURNS = [
    {"speaker": "caller", "text": "voglio parlare con un operatore per la bolletta di 45 euro", "agent_id": None},
    {"speaker": "agent", "text": "Ti passo subito a un operatore umano.", "agent_id": "billing", "tools": ["transfer_to_human"]},
]
CRITERIA = [
    EvaluationCriterion(id="passato_operatore", name="Passato a operatore", prompt="Il chiamante viene passato a un operatore umano."),
    EvaluationCriterion(id="meteo", name="Meteo", prompt="Si parla di previsioni meteorologiche nevicate."),
]
DATA = [
    DataCollectionItem(id="vuole_operatore", type="boolean", description="Il chiamante chiede un operatore."),
    DataCollectionItem(id="importo", type="number", description="Importo della bolletta citato dal chiamante."),
    DataCollectionItem(id="motivo", type="string", description="Motivo della chiamata."),
]


class _StubLLM(LLMProvider):
    def __init__(self, reply: str):
        self.reply = reply
        self.calls: list[tuple[str, str]] = []

    def classify(self, *a, **k):  # pragma: no cover - not used
        raise AssertionError

    def respond(self, *a, **k):  # pragma: no cover - not used
        raise AssertionError

    def summarize(self, *a, **k):  # pragma: no cover - not used
        raise AssertionError

    def complete(self, system: str, user: str, max_tokens: int = 800) -> str:
        self.calls.append((system, user))
        return self.reply


class _NoCompletion(_StubLLM):
    def complete(self, system: str, user: str, max_tokens: int = 800) -> str:
        return LLMProvider.complete(self, system, user, max_tokens)


def test_heuristic_does_not_judge_natural_language_criteria():
    """D11: without a model, a criterion written in prose is `unknown` (and
    says why) — no more word-overlap verdicts like "Agente giusto: fallito"."""
    result = analyze(TURNS, CRITERIA, DATA, FakeProvider())
    assert result.method == "heuristic"
    assert all(c.result == "unknown" for c in result.criteria)
    assert all("provider LLM" in c.rationale for c in result.criteria)

    data = {d.item_id: d.value for d in result.data}
    assert data["vuole_operatore"] is True
    assert data["importo"] == 45.0
    assert data["motivo"].startswith("voglio parlare")
    assert result.call_successful == "unknown"


def test_empty_transcript_is_unknown_not_a_crash():
    result = analyze([], CRITERIA, DATA, FakeProvider())
    assert all(c.result == "unknown" for c in result.criteria)
    assert all(d.value is None for d in result.data)
    assert result.call_successful == "unknown"


def test_llm_path_parses_fenced_json_and_coerces_types():
    stub = _StubLLM(
        "Ecco l'analisi:\n```json\n"
        '{"summary": "Il chiamante voleva un operatore.", '
        '"criteria": [{"id": "passato_operatore", "result": "SUCCESS", "rationale": "passato"}, '
        '{"id": "meteo", "result": "maybe", "rationale": "boh"}], '
        '"data": [{"id": "vuole_operatore", "value": "true", "rationale": "detto"}, '
        '{"id": "importo", "value": "45", "rationale": "citato"}]}\n```'
    )
    result = analyze(TURNS, CRITERIA, DATA, stub)

    assert result.method == "llm"
    assert result.provider == "_StubLLM"
    assert result.summary == "Il chiamante voleva un operatore."
    by_id = {c.criterion_id: c.result for c in result.criteria}
    assert by_id == {"passato_operatore": "success", "meteo": "unknown"}  # invalid label -> unknown
    data = {d.item_id: d.value for d in result.data}
    assert data == {"vuole_operatore": True, "importo": 45.0, "motivo": None}  # missing -> None
    # The prompt really carried the criteria, data items and transcript.
    _, user = stub.calls[0]
    assert "passato_operatore" in user and "importo" in user and "bolletta di 45 euro" in user


def test_llm_garbage_reply_is_reported_not_hidden():
    result = analyze(TURNS, CRITERIA, DATA, _StubLLM("non so cosa dire"))
    assert result.method == "llm"
    assert "fallita" in result.summary
    assert all(c.result == "unknown" for c in result.criteria)


def test_provider_without_completion_falls_back_to_heuristic():
    result = analyze(TURNS, CRITERIA, DATA, _NoCompletion(""))
    assert result.method == "heuristic"


def test_call_successful_rules():
    def r(*results):
        return AnalysisResult("llm", "x", "", [CriterionResult(str(i), v, "") for i, v in enumerate(results)])

    assert r("success", "success").call_successful == "success"
    assert r("success", "unknown").call_successful == "unknown"
    assert r("success", "failure").call_successful == "failure"
    assert r().call_successful == "unknown"


def test_as_dict_from_dict_round_trip():
    result = analyze(TURNS, CRITERIA, DATA, FakeProvider())
    data = result.as_dict()
    assert data["call_successful"] == result.call_successful
    assert AnalysisResult.from_dict(data) == result


def test_defaults_are_well_formed():
    assert [c.id for c in analysis.DEFAULT_CRITERIA] == ["richiesta_risolta", "agente_corretto", "senza_operatore"]
    assert all(c.kind in analysis.KINDS for c in analysis.DEFAULT_CRITERIA)
    assert all(d.type in analysis.DATA_TYPES for d in analysis.DEFAULT_DATA_ITEMS)


# ---- D11: structural criteria ----

ROUTED = [
    {"speaker": "caller", "text": "il wifi non va", "agent_id": None},
    {"speaker": "agent", "text": "ti passo al tecnico", "agent_id": "router"},
    {"speaker": "caller", "text": "ok", "agent_id": None},
    {"speaker": "agent", "text": "riavvia il modem", "agent_id": "tech_support", "tools": ["knowledge_lookup"]},
]


def _crit(kind, expected=()):
    return EvaluationCriterion(id="c", name="c", prompt="", kind=kind, expected=list(expected))


def _one(turns, criterion, provider=None):
    return analyze(turns, [criterion], [], provider or FakeProvider()).criteria[0]


def test_final_agent_without_expected_means_left_the_entry_agent():
    assert _one(ROUTED, _crit(analysis.KIND_FINAL_AGENT)).result == "success"
    stayed = [t if t.get("agent_id") is None else {**t, "agent_id": "router"} for t in ROUTED]
    r = _one(stayed, _crit(analysis.KIND_FINAL_AGENT))
    assert r.result == "failure" and "router" in r.rationale


def test_final_agent_with_expected_ids():
    assert _one(ROUTED, _crit(analysis.KIND_FINAL_AGENT, ["tech_support", "tech_internet"])).result == "success"
    assert _one(ROUTED, _crit(analysis.KIND_FINAL_AGENT, ["billing"])).result == "failure"


def test_tool_used_and_not_used():
    assert _one(ROUTED, _crit(analysis.KIND_TOOL_USED, ["knowledge_lookup"])).result == "success"
    assert _one(ROUTED, _crit(analysis.KIND_TOOL_NOT_USED, ["knowledge_lookup"])).result == "failure"
    assert _one(TURNS, _crit(analysis.KIND_TOOL_NOT_USED, ["transfer_to_human"])).result == "failure"
    assert _one(ROUTED, _crit(analysis.KIND_TOOL_NOT_USED, ["transfer_to_human"])).result == "success"


def test_structural_criteria_never_reach_the_llm_and_keep_their_order():
    stub = _StubLLM('{"summary": "s", "criteria": [{"id": "giudicato", "result": "success", "rationale": "r"}], "data": []}')
    criteria = [
        EvaluationCriterion(id="strutturale", name="s", prompt="", kind=analysis.KIND_FINAL_AGENT),
        EvaluationCriterion(id="giudicato", name="g", prompt="Il chiamante è soddisfatto."),
    ]
    result = analyze(ROUTED, criteria, [], stub)
    assert [c.criterion_id for c in result.criteria] == ["strutturale", "giudicato"]
    assert [c.result for c in result.criteria] == ["success", "success"]
    _, user = stub.calls[0]
    assert "strutturale" not in user and "giudicato" in user


def test_default_criteria_without_keys_give_real_verdicts_on_structure():
    result = analyze(ROUTED, analysis.DEFAULT_CRITERIA, [], FakeProvider())
    by_id = {c.criterion_id: c.result for c in result.criteria}
    assert by_id == {"richiesta_risolta": "unknown", "agente_corretto": "success", "senza_operatore": "success"}
