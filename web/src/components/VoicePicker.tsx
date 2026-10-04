import type { AgentVoiceOverride } from '../types'

interface Props {
  value: AgentVoiceOverride
  onChange: (value: AgentVoiceOverride) => void
}

// A handful of ElevenLabs' own stock voice ids (publicly documented
// presets, not something private to this account) — enough to make this a
// real dropdown instead of a free-text field (blocco 2's "real pickers"
// item), with "custom" as the escape hatch for a cloned/other voice id.
const PRESETS = [
  { id: '21m00Tcm4TlvDq8ikWAM', label: 'Rachel — calma, misurata' },
  { id: 'EXAVITQu4vr4xnSDxMaL', label: 'Bella — calda, informale' },
  { id: 'VR6AewLTigWG4xSOukaG', label: 'Arnold — profonda, autorevole' },
  { id: 'pNInz6obpgDQGcFmaJgB', label: 'Adam — neutra, professionale' },
]

export function VoicePicker({ value, onChange }: Props) {
  const isPreset = PRESETS.some((p) => p.id === value.voice_id)
  const isCustom = value.voice_id !== '' && !isPreset

  return (
    <div className="field">
      <label>Voce (ElevenLabs, blocco 2)</label>
      <select
        value={isCustom ? '__custom__' : value.voice_id}
        onChange={(e) => {
          const next = e.target.value
          onChange({ ...value, voice_id: next === '__custom__' ? value.voice_id || ' ' : next })
        }}
      >
        <option value="">Eredita dalla famiglia (nessuna voce dedicata)</option>
        {PRESETS.map((p) => (
          <option key={p.id} value={p.id}>
            {p.label}
          </option>
        ))}
        <option value="__custom__">Voice id personalizzato…</option>
      </select>
      {isCustom && (
        <input
          placeholder="voice_id ElevenLabs"
          value={value.voice_id.trim()}
          onChange={(e) => onChange({ ...value, voice_id: e.target.value })}
        />
      )}
      {value.voice_id && (
        <div className="voice-picker__sliders">
          <label className="voice-picker__slider">
            Stabilità {value.voice_stability ?? 0.5}
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={value.voice_stability ?? 0.5}
              onChange={(e) => onChange({ ...value, voice_stability: Number(e.target.value) })}
            />
          </label>
          <label className="voice-picker__slider">
            Velocità {value.voice_speed ?? 1}
            <input
              type="range"
              min={0.7}
              max={1.3}
              step={0.05}
              value={value.voice_speed ?? 1}
              onChange={(e) => onChange({ ...value, voice_speed: Number(e.target.value) })}
            />
          </label>
        </div>
      )}
      <p className="field-hint">
        Collegata davvero al TTS (fixa D1) — vedi voice/agent.py. Non verificata su una chiamata
        reale in questo ambiente (niente credenziali LiveKit/ElevenLabs qui).
      </p>
    </div>
  )
}
