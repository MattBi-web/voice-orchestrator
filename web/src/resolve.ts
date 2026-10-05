import type { Agent, Catalog, ModelSettings } from './types'

/** Client-side mirror of project.py's resolution rules (blocco 8), so the
 * agent page's pipeline updates while you edit, before saving. The server's
 * /pipeline endpoint (shown in the Developer tab) stays the source of truth;
 * tests in tests/test_projects.py pin the rules both follow:
 * - every field inherits the project's when empty;
 * - an agent that switches provider doesn't inherit the project's model or
 *   voice (they belong to the other provider). */

export type Piece = 'stt' | 'router' | 'llm' | 'tts'

export interface Resolved {
  piece: Piece
  provider: string
  model: string
  source: 'agent' | 'project' | 'deployment'
  detail: string
  /** False when the catalog says this provider can't run on this server. */
  available: boolean
}

type Overrides = Pick<
  Agent,
  | 'stt_provider'
  | 'stt_model'
  | 'stt_language'
  | 'tts_provider'
  | 'tts_model'
  | 'voice_id'
  | 'voice_stability'
  | 'voice_speed'
  | 'llm_provider'
  | 'llm_model'
  | 'llm_temperature'
>

const set = (v: unknown) => v !== '' && v !== null && v !== undefined

function pick<T extends Record<string, unknown>>(
  agentProvider: string,
  agentValues: T,
  projectProvider: string,
  projectValues: T,
): { provider: string; values: T; source: 'agent' | 'project' } {
  if (agentProvider && agentProvider !== projectProvider) {
    return { provider: agentProvider, values: agentValues, source: 'agent' }
  }
  const values = Object.fromEntries(
    Object.keys(agentValues).map((k) => [k, set(agentValues[k]) ? agentValues[k] : projectValues[k]]),
  ) as T
  const overridden = Boolean(agentProvider) || Object.values(agentValues).some(set)
  return { provider: projectProvider, values, source: overridden ? 'agent' : 'project' }
}

export function resolve(agent: Overrides, s: ModelSettings, catalog: Catalog | null, isRoot = false): Resolved[] {
  const ok = (component: 'stt' | 'tts' | 'llm', id: string) =>
    !catalog || id === 'fake' || id === '' || (catalog[component].find((p) => p.id === id)?.available ?? false)
  const label = (component: 'stt' | 'tts' | 'llm', id: string) =>
    catalog?.[component].find((p) => p.id === id)?.label ?? (id || '—')
  const voiceLabel = (provider: string, id: string) =>
    catalog?.tts.find((p) => p.id === provider)?.voices.find((v) => v.id === id)?.label ?? (id || 'default voice')

  const stt = pick(
    agent.stt_provider,
    { model: agent.stt_model, language: agent.stt_language },
    s.stt_provider,
    { model: s.stt_model, language: s.stt_language },
  )
  const tts = pick(
    agent.tts_provider,
    { model: agent.tts_model, voice: agent.voice_id },
    s.tts_provider,
    { model: s.tts_model, voice: s.voice_id },
  )
  const llm = pick(
    agent.llm_provider,
    { model: agent.llm_model, temperature: agent.llm_temperature as unknown },
    s.llm_provider,
    { model: s.llm_model, temperature: s.llm_temperature as unknown },
  )
  const llmProvider = llm.provider || 'fake'
  const routerProvider = s.router_provider || s.llm_provider || 'fake'
  const routerModel = s.router_provider ? s.router_model : s.router_model || s.llm_model

  return [
    {
      piece: 'stt',
      provider: label('stt', stt.provider),
      model: (stt.values.model as string) || 'default model',
      source: stt.source,
      available: ok('stt', stt.provider),
      detail: languageName((stt.values.language as string) || ''),
    },
    {
      piece: 'router',
      provider: routerProvider === 'fake' ? 'Gate and keywords only' : label('llm', routerProvider),
      model: routerProvider === 'fake' ? '' : routerModel || 'default model',
      source: s.router_provider || s.llm_provider ? 'project' : 'deployment',
      available: ok('llm', routerProvider),
      detail: isRoot ? 'Picks who answers each turn' : 'Picks among this agent’s specialists',
    },
    {
      piece: 'llm',
      provider: llmProvider === 'fake' ? 'No model' : label('llm', llmProvider),
      model: llmProvider === 'fake' ? '' : (llm.values.model as string) || 'default model',
      source: llm.provider ? llm.source : 'deployment',
      available: ok('llm', llmProvider),
      detail:
        llmProvider === 'fake'
          ? 'Placeholder replies'
          : set(llm.values.temperature)
            ? `Temperature ${llm.values.temperature}`
            : '',
    },
    {
      piece: 'tts',
      provider: label('tts', tts.provider),
      model: (tts.values.model as string) || 'default model',
      source: tts.source,
      available: ok('tts', tts.provider),
      detail: voiceLabel(tts.provider, (tts.values.voice as string) || ''),
    },
  ]
}

const LANGUAGES: Record<string, string> = {
  multi: 'Any language',
  it: 'Italian',
  en: 'English',
  es: 'Spanish',
  fr: 'French',
  de: 'German',
}

export const languageName = (code: string) => LANGUAGES[code] ?? (code || 'Any language')
