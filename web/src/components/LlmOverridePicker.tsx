import type { AgentLlmOverride } from '../types'

interface Props {
  value: AgentLlmOverride
  onChange: (value: AgentLlmOverride) => void
}

const PROVIDERS = ['fake', 'anthropic', 'openai', 'gemini']

/** Blocco 2: an agent can pin its own provider/model/temperature instead
 * of inheriting the family-wide VOICE_ORCH_PROVIDER. "" provider = inherit
 * — see orchestrator.py's get_provider_for_agent(). classify() never uses
 * this (routing stays on the call's default provider on purpose), only
 * the agent's own reply does. */
export function LlmOverridePicker({ value, onChange }: Props) {
  const overridden = value.llm_provider !== ''

  return (
    <div className="field">
      <label>LLM per questo agente (blocco 2)</label>
      <select
        value={value.llm_provider}
        onChange={(e) => onChange({ ...value, llm_provider: e.target.value })}
      >
        <option value="">Eredita dalla famiglia (VOICE_ORCH_PROVIDER)</option>
        {PROVIDERS.map((p) => (
          <option key={p} value={p}>
            {p}
          </option>
        ))}
      </select>
      {overridden && (
        <>
          <input
            placeholder="modello (opzionale, es. claude-haiku-4-5) — vuoto = default del provider"
            value={value.llm_model}
            onChange={(e) => onChange({ ...value, llm_model: e.target.value })}
          />
          <label className="voice-picker__slider">
            Temperature {value.llm_temperature ?? '(default del provider)'}
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={value.llm_temperature ?? 0.5}
              onChange={(e) => onChange({ ...value, llm_temperature: Number(e.target.value) })}
            />
          </label>
          {value.llm_temperature !== null && (
            <button type="button" className="btn-link" onClick={() => onChange({ ...value, llm_temperature: null })}>
              Rimuovi override temperature
            </button>
          )}
        </>
      )}
      <p className="field-hint">
        Solo respond() usa questo override — classify() resta sul provider di default della
        chiamata, per mantenere il routing deterministico/economico.
      </p>
    </div>
  )
}
