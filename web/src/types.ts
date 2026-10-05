// Mirrors src/voice_orchestrator/webapi/schemas.py — kept hand-in-sync
// rather than code-generated, since the schema is small and stable enough
// that a generator would add more ceremony than it saves right now.

export interface ToolBinding {
  id: string
  condition: string
}

// Blocco 2 fields: "" / null means "inherit the family/global default" —
// see agents/registry.py's AgentSpec docstring for the full rationale.
export interface AgentLlmOverride {
  llm_provider: string
  llm_model: string
  llm_temperature: number | null
}

export interface AgentVoiceOverride {
  voice_id: string
  voice_stability: number | null
  voice_speed: number | null
  // Blocco 8: the rest of the pipeline, "" = inherit the project's.
  tts_provider: string
  tts_model: string
  stt_provider: string
  stt_model: string
  stt_language: string
}

/** Blocco 8: a project's default models (project.ModelSettings). */
export interface ModelSettings {
  stt_provider: string
  stt_model: string
  stt_language: string
  tts_provider: string
  tts_model: string
  voice_id: string
  voice_stability: number | null
  voice_speed: number | null
  llm_provider: string
  llm_model: string
  llm_temperature: number | null
  router_provider: string
  router_model: string
}

export interface Project {
  id: string
  name: string
  description: string
  created_at: string
  updated_at: string
  kind: 'single' | 'workflow'
  agent_count: number
  root_agent: { id: string; name: string } | null
  settings: ModelSettings
  call_count?: number
}

export interface Template {
  id: 'single' | 'workflow' | 'demo'
  name: string
  description: string
  agent_count: number
}

export type Component = 'stt' | 'tts' | 'llm'

export interface CatalogProvider {
  component: Component
  id: string
  label: string
  models: string[]
  default_model: string
  voices: { id: string; label: string }[]
  languages: string[]
  available: boolean
  missing: string
  note: string
}

export type Catalog = Record<Component, CatalogProvider[]>

export interface PipelineStep {
  component: 'stt' | 'router' | 'llm' | 'tts'
  provider: string
  model: string
  source: 'agent' | 'project' | 'deployment'
  available: boolean
  language?: string
  voice_id?: string
  temperature?: number | null
}

export interface AgentPipeline {
  agent_id: string
  steps: PipelineStep[]
  routing: { children: { id: string; name: string; eligibility: string; triggers: string[] }[] }
  tools: ToolBinding[]
  knowledge: string[]
}

export interface Agent extends AgentLlmOverride, AgentVoiceOverride {
  id: string
  parent_id: string | null
  name: string
  description: string
  system_prompt: string
  eligibility: string
  triggers: string[]
  tools: ToolBinding[]
  knowledge: string[]
  first_message: string
  // Blocco 4: where the graph view last left this node, null = auto-layout.
  layout_x: number | null
  layout_y: number | null
  children: Agent[]
  children_ids: string[]
}

export interface AgentInput extends AgentLlmOverride, AgentVoiceOverride {
  id: string
  parent_id: string | null
  name: string
  description: string
  system_prompt: string
  eligibility: string
  triggers: string[]
  tools: ToolBinding[]
  knowledge: string[]
  first_message: string
}

export interface AgentUpdateInput extends AgentLlmOverride, AgentVoiceOverride {
  name: string
  description: string
  system_prompt: string
  eligibility: string
  triggers: string[]
  tools: ToolBinding[]
  knowledge: string[]
  first_message: string
}

export interface AgentLayoutUpdate {
  layout_x: number
  layout_y: number
}

export interface AgentReparentRequest {
  parent_id: string
}

/** Live call events (blocco 7, fase C): published by the voice worker on the
 * LiveKit data channel, topic `vo.events` (call_events.py). */
export type CallEvent =
  | { type: 'greeting'; agent_id: string; agent_name: string; text: string }
  | {
      type: 'turn'
      seq: number
      caller: string
      from_agent_id: string
      from_agent_name: string
      agent_id: string
      agent_name: string
      resolved_by: string
      eligible: string[]
      excluded: { id: string; name: string; rule: string }[]
      keyword: string | null
      handed_off: boolean
      tools: string[]
      reply: string
      latency_ms: number | null
      simulated: boolean
      /** Text tests only: end_call ran and the conversation is over. */
      ended?: boolean
    }
  | { type: 'ended'; reason: string }

export interface TestRouteResult {
  agent_id: string
  agent_name: string
  resolved_by: string
  eligible_agents: string[]
  handed_off: boolean
  reply: string
  tool_ids_used: string[]
  /** Class name of the provider that composed `reply` (after per-agent overrides). */
  provider: string
}

export interface LlmStatus {
  requested: string
  resolved: string
  real: boolean
}

export interface VoiceStatus {
  configured: boolean
}

export interface VoiceToken {
  token: string
  url: string
  room: string
  identity: string
}

// Mirrors call_log.CallRecord.as_dict() — the agent-builder's call-log
// dashboard (Dashboard.tsx) reads these straight from GET /api/calls*.
export interface CallRecord {
  call_id: string
  project_id: string
  source: 'chat' | 'voice' | 'route_test'
  channel: string
  started_at: string
  ended_at: string
  duration_seconds: number
  turn_count: number
  final_agent_id: string | null
  resolved_by_counts: Record<string, number>
  tool_counts: Record<string, number>
  handoffs: number
  // Latest analysis verdict, null if the call was never analyzed (list view only).
  call_successful?: Verdict | null
}

export interface CallDayCount {
  date: string
  count: number
}

export interface CallStats {
  total_calls: number
  total_minutes: number
  avg_duration_seconds: number
  handoff_rate: number
  resolved_by_totals: Record<string, number>
  tool_totals: Record<string, number>
  calls_by_source: Record<string, number>
  calls_by_day: CallDayCount[]
  analyzed_calls: number
  analysis_outcomes: Record<Verdict, number>
  success_rate: number | null
}

// Mirrors McpServerIn/McpServerOut in schemas.py.
export interface McpServer {
  name: string
  command: string
  args: string[]
}

// Blocco 3 — mirrors WebhookParamSchema/WebhookToolIn/WebhookToolOut in
// schemas.py. A header value may be the literal string "{{secret:NAME}}",
// resolved server-side from VOICE_ORCH_SECRET_NAME at call time — this type
// (and the form that edits it) never carries a real secret value.
export interface WebhookParam {
  name: string
  source: 'slot' | 'literal'
  value: string
  type: 'string' | 'number' | 'boolean'
}

export type WebhookMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

export interface WebhookTool {
  name: string
  description: string
  url: string
  method: WebhookMethod
  headers: Record<string, string>
  params: WebhookParam[]
  triggers: string[]
  timeout_seconds: number
}

// Mirrors WebhookExecutionOut / tools/webhook_log.py's Execution.
export interface WebhookExecution {
  tool_name: string
  call_id: string
  agent_id: string
  url: string
  method: string
  ok: boolean
  status_code: number | null
  latency_ms: number
  error: string
  at: string
}

// ---- Conversations + post-call analysis (call_log.transcript_from_session,
// analysis.AnalysisResult, webapi/analysis_repository.py) ----

export type Verdict = 'success' | 'failure' | 'unknown'

export interface RoutingInfo {
  resolved_by: string
  chosen_agent: string | null
  eligible_agents: string[]
  latency_ms: number
  reason: string
}

export interface TranscriptTurn {
  speaker: 'caller' | 'agent'
  text: string
  agent_id: string | null
  timestamp: string
  routing?: RoutingInfo
  handoff?: { from_agent: string; to_agent: string }
  tools?: string[]
}

export interface CriterionResult {
  criterion_id: string
  result: Verdict
  rationale: string
}

export interface DataCollectionResult {
  item_id: string
  value: string | number | boolean | null
  rationale: string
}

export interface CallAnalysis {
  method: 'heuristic' | 'llm'
  provider: string
  summary: string
  criteria: CriterionResult[]
  data: DataCollectionResult[]
  call_successful: Verdict
  analyzed_at: string
}

export interface CallDetail extends CallRecord {
  turns: TranscriptTurn[]
  analysis: CallAnalysis | null
}

export type DataItemType = 'string' | 'boolean' | 'integer' | 'number'

/** D11: `llm` is judged by a model from `prompt`; the others are checked
 * against the transcript's structure, with `expected` as their argument. */
export type CriterionKind = 'llm' | 'final_agent' | 'tool_used' | 'tool_not_used'

export interface Criterion {
  id: string
  name: string
  prompt: string
  kind: CriterionKind
  expected: string[]
}

export interface DataItem {
  id: string
  type: DataItemType
  description: string
}

export interface AnalysisConfig {
  criteria: Criterion[]
  data_items: DataItem[]
}

export interface ExportResult {
  path: string
  agent_count: number
}

// ---- blocco 5: knowledge base ----

export interface KnowledgeDoc {
  name: string
  /** false: an agent references this name but there's no file for it. */
  exists: boolean
  size_bytes: number
  chunk_count: number
  /** "" for files with no recorded source (the bundled demo files). */
  source_type: '' | 'text' | 'file' | 'url'
  source_url: string
  updated_at: string
  used_by: string[]
}

export interface KnowledgeChunk {
  index: number
  text: string
}

export interface KnowledgeDocDetail extends KnowledgeDoc {
  content: string
  chunks: KnowledgeChunk[]
}

export interface KnowledgeHit {
  document: string
  index: number
  text: string
  score: number
}

export interface KnowledgeSearchResult {
  documents: string[]
  hits: KnowledgeHit[]
}

