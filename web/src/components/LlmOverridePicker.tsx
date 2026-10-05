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
      <label>Language model</label>
      <select
        value={value.llm_provider}
        onChange={(e) => onChange({ ...value, llm_provider: e.target.value })}
      >
        <option value="">Same as the rest of the family</option>
        {PROVIDERS.map((p) => (
          <option key={p} value={p}>
            {p}
          </option>
        ))}
      </select>
      {overridden && (
        <>
          <input
            placeholder="Model, e.g. claude-haiku-4-5 (empty: provider default)"
            value={value.llm_model}
            onChange={(e) => onChange({ ...value, llm_model: e.target.value })}
          />
          <label className="voice-picker__slider">
            Temperature {value.llm_temperature ?? '(provider default)'}
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
              Reset temperature
            </button>
          )}
        </>
      )}
      <p className="field-hint">
        Used for this agent's replies only. Routing always uses the family's model, so which agent answers never
        depends on which one is asked.
      </p>
    </div>
  )
}
