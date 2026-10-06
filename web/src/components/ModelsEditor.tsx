import { useState } from 'react'
import type { Catalog, CatalogProvider, Component, ModelSettings } from '../types'
import { languageName } from '../resolve'

/** Model choices for each piece of the pipeline (blocco 8), in two modes:
 * - project: the defaults every agent in the project starts from;
 * - agent: per piece, "use the project's" or override it.
 * Providers come from /api/catalog; one that can't run on this server
 * (missing key or package) is listed but can't be picked. Models are
 * suggestions: "Other…" accepts any id the provider knows. */

export type ModelFields = Partial<ModelSettings>

type Section = 'stt' | 'router' | 'llm' | 'tts'

const SECTIONS: { id: Section; title: string; what: string; component: Component }[] = [
  { id: 'stt', title: 'Speech recognition', what: 'Speech to text: turns what the caller says into text.', component: 'stt' },
  {
    id: 'router',
    title: 'Router model',
    what: 'Only used when the gate and the keywords can’t decide who answers. A small, fast model is usually enough.',
    component: 'llm',
  },
  { id: 'llm', title: 'Language model', what: 'Writes the agent’s replies.', component: 'llm' },
  { id: 'tts', title: 'Voice', what: 'Text to speech: the voice the caller hears.', component: 'tts' },
]

const FIELDS: Record<Section, (keyof ModelSettings)[]> = {
  stt: ['stt_provider', 'stt_model', 'stt_language'],
  router: ['router_provider', 'router_model'],
  llm: ['llm_provider', 'llm_model', 'llm_temperature'],
  tts: ['tts_provider', 'tts_model', 'voice_id', 'voice_stability', 'voice_speed'],
}

const providerKey: Record<Section, keyof ModelSettings> = {
  stt: 'stt_provider',
  router: 'router_provider',
  llm: 'llm_provider',
  tts: 'tts_provider',
}
const modelKey: Record<Section, keyof ModelSettings> = {
  stt: 'stt_model',
  router: 'router_model',
  llm: 'llm_model',
  tts: 'tts_model',
}

interface Props {
  mode: 'project' | 'agent'
  value: ModelFields
  /** The project's settings: what an agent inherits. */
  project: ModelSettings
  catalog: Catalog | null
  onChange: (patch: ModelFields) => void
  /** Narrow column (agent page): voice first, one field per row. */
  compact?: boolean
}

const COMPACT_ORDER: Section[] = ['tts', 'stt', 'llm']

export function ModelsEditor({ mode, value, project, catalog, onChange, compact = false }: Props) {
  const sections = compact
    ? COMPACT_ORDER.map((id) => SECTIONS.find((s) => s.id === id)!).filter((s) => mode === 'project' || s.id !== 'router')
    : SECTIONS.filter((s) => mode === 'project' || s.id !== 'router')
  return (
    <div className={compact ? 'models models--compact' : 'models'}>
      {sections.map((section) => (
        <ModelSection key={section.id} section={section} mode={mode} value={value} project={project} catalog={catalog} onChange={onChange} />
      ))}
    </div>
  )
}

function ModelSection({
  section,
  mode,
  value,
  project,
  catalog,
  onChange,
}: { section: (typeof SECTIONS)[number] } & Props) {
  const keys = FIELDS[section.id]
  const overridden = mode === 'agent' && keys.some((k) => value[k] !== '' && value[k] !== null && value[k] !== undefined)
  const editing = mode === 'project' || overridden
  // In agent mode the form shows the project's values until overridden.
  const shown: ModelFields = editing ? { ...(mode === 'agent' ? project : {}), ...pickDefined(value, keys) } : project
  const providers = catalog?.[section.component] ?? []
  const pid = (shown[providerKey[section.id]] as string) ?? ''
  const provider = providers.find((p) => p.id === pid)

  const set = (patch: ModelFields) => {
    if (mode === 'agent' && !overridden) {
      // First edit of an inherited section: start from the project's values.
      onChange({ ...pickDefined(project, keys), ...patch })
    } else onChange(patch)
  }

  const switchProvider = (next: string) => {
    const p = providers.find((x) => x.id === next)
    const patch: ModelFields = { [providerKey[section.id]]: next, [modelKey[section.id]]: p?.default_model ?? '' }
    if (section.id === 'tts') Object.assign(patch, { voice_id: '', voice_stability: null, voice_speed: null })
    if (section.id === 'stt') patch.stt_language = p?.languages[0] ?? ''
    set(patch)
  }

  return (
    <section className={`models__section${editing ? '' : ' models__section--inherited'}`} aria-labelledby={`models-${section.id}`}>
      <header className="models__head">
        <div>
          <h3 id={`models-${section.id}`}>{section.title}</h3>
          <p>{section.what}</p>
        </div>
        {mode === 'agent' && (
          <div className="seg" role="group" aria-label={`${section.title}: project default or override`}>
            <button
              type="button"
              aria-pressed={!overridden}
              onClick={() => onChange(Object.fromEntries(keys.map((k) => [k, isNumeric(k) ? null : ''])))}
            >
              Default
            </button>
            <button
              type="button"
              aria-pressed={overridden}
              onClick={() => {
                if (overridden) return
                const start = pid || providers.find((p) => p.available && p.id !== 'fake')?.id || providers[0]?.id || ''
                set({ [providerKey[section.id]]: start })
              }}
            >
              Override
            </button>
          </div>
        )}
      </header>

      <fieldset className="models__fields" disabled={!editing}>
        <label className="models__field">
          <span>Provider</span>
          <ProviderSelect
            providers={providers}
            value={pid}
            emptyLabel={
              section.id === 'router'
                ? 'Same as the language model'
                : section.id === 'llm'
                  ? 'Server default'
                  : undefined
            }
            onChange={switchProvider}
          />
        </label>
        {!(section.id === 'router' && !pid) && provider && provider.id !== 'fake' && (
          <label className="models__field">
            <span>Model</span>
            <SuggestInput
              options={provider.models.map((m) => ({ id: m, label: m }))}
              value={(shown[modelKey[section.id]] as string) ?? ''}
              placeholder={provider.default_model}
              onChange={(v) => set({ [modelKey[section.id]]: v })}
            />
          </label>
        )}
        {section.id === 'stt' && provider && (
          <label className="models__field">
            <span>Language</span>
            <select value={shown.stt_language ?? ''} onChange={(e) => set({ stt_language: e.target.value })}>
              {(provider.languages.length ? provider.languages : ['multi']).map((l) => (
                <option key={l} value={l}>
                  {languageName(l)}
                </option>
              ))}
            </select>
          </label>
        )}
        {section.id === 'llm' && provider && provider.id !== 'fake' && (
          <label className="models__field">
            <span>Temperature</span>
            <input
              type="number"
              min={0}
              max={1}
              step={0.1}
              placeholder="model default"
              value={shown.llm_temperature ?? ''}
              onChange={(e) => set({ llm_temperature: e.target.value === '' ? null : Number(e.target.value) })}
            />
          </label>
        )}
        {section.id === 'tts' && provider && (
          <>
            <label className="models__field">
              <span>Voice</span>
              <SuggestInput
                options={provider.voices}
                value={shown.voice_id ?? ''}
                placeholder="default voice"
                otherLabel="Voice id…"
                onChange={(v) => set({ voice_id: v })}
              />
            </label>
            {provider.id === 'elevenlabs' && (
              <>
                <label className="models__field models__field--range">
                  <span>
                    Stability <output>{shown.voice_stability ?? 'default'}</output>
                  </span>
                  <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.05}
                    value={shown.voice_stability ?? 0.5}
                    onChange={(e) => set({ voice_stability: Number(e.target.value) })}
                  />
                </label>
                <label className="models__field models__field--range">
                  <span>
                    Speed <output>{shown.voice_speed ?? 'default'}</output>
                  </span>
                  <input
                    type="range"
                    min={0.7}
                    max={1.2}
                    step={0.05}
                    value={shown.voice_speed ?? 1}
                    onChange={(e) => set({ voice_speed: Number(e.target.value) })}
                  />
                </label>
              </>
            )}
          </>
        )}
      </fieldset>
      {provider && !provider.available && <p className="models__warn">{provider.label} can’t run on this server: {provider.missing}.</p>}
      {provider?.note && editing && <p className="models__note">{provider.note}</p>}
    </section>
  )
}

function pickDefined(v: ModelFields, keys: (keyof ModelSettings)[]): ModelFields {
  return Object.fromEntries(keys.filter((k) => v[k] !== '' && v[k] !== null && v[k] !== undefined).map((k) => [k, v[k]]))
}

const isNumeric = (k: string) => k === 'llm_temperature' || k === 'voice_stability' || k === 'voice_speed'

function ProviderSelect({
  providers,
  value,
  emptyLabel,
  onChange,
}: {
  providers: CatalogProvider[]
  value: string
  emptyLabel?: string
  onChange: (id: string) => void
}) {
  const known = providers.some((p) => p.id === value)
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      {emptyLabel !== undefined && <option value="">{emptyLabel}</option>}
      {!known && value && <option value={value}>{value} (not in the catalog)</option>}
      {providers.map((p) => (
        <option key={p.id} value={p.id} disabled={!p.available && p.id !== value}>
          {p.label}
          {p.available ? '' : ` (${p.missing})`}
        </option>
      ))}
    </select>
  )
}

/** A select of suggestions plus "Other…", which turns into a text input
 * for an id not in the list (a cloned voice, a newer model). */
function SuggestInput({
  options,
  value,
  placeholder,
  otherLabel = 'Other…',
  onChange,
}: {
  options: { id: string; label: string }[]
  value: string
  placeholder: string
  otherLabel?: string
  onChange: (v: string) => void
}) {
  const listed = options.some((o) => o.id === value)
  const [custom, setCustom] = useState(!listed && value !== '')
  if (custom || (!listed && value !== '')) {
    return (
      <span className="models__custom">
        <input value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
        <button
          type="button"
          className="btn-link"
          onClick={() => {
            setCustom(false)
            onChange(options[0]?.id ?? '')
          }}
        >
          List
        </button>
      </span>
    )
  }
  return (
    <select
      value={value}
      onChange={(e) => {
        if (e.target.value === '__other__') {
          setCustom(true)
          onChange('')
        } else onChange(e.target.value)
      }}
    >
      {!options.some((o) => o.id === '') && <option value="">{placeholder}</option>}
      {options.map((o) => (
        <option key={o.id} value={o.id}>
          {o.label}
        </option>
      ))}
      <option value="__other__">{otherLabel}</option>
    </select>
  )
}
