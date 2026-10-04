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

export interface TestRouteResult {
  agent_id: string
  agent_name: string
  resolved_by: string
  eligible_agents: string[]
  handed_off: boolean
  reply: string
  tool_ids_used: string[]
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

export interface Criterion {
  id: string
  name: string
  prompt: string
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
