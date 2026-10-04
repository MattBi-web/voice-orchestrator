// Mirrors src/voice_orchestrator/webapi/schemas.py — kept hand-in-sync
// rather than code-generated, since the schema is small and stable enough
// that a generator would add more ceremony than it saves right now.

export interface ToolBinding {
  id: string
  condition: string
}

export interface Agent {
  id: string
  parent_id: string | null
  name: string
  description: string
  system_prompt: string
  eligibility: string
  voice: string
  triggers: string[]
  tools: ToolBinding[]
  knowledge: string[]
  children: Agent[]
  children_ids: string[]
}

export interface AgentInput {
  id: string
  parent_id: string | null
  name: string
  description: string
  system_prompt: string
  eligibility: string
  voice: string
  triggers: string[]
  tools: ToolBinding[]
  knowledge: string[]
}

export interface AgentUpdateInput {
  name: string
  description: string
  system_prompt: string
  eligibility: string
  voice: string
  triggers: string[]
  tools: ToolBinding[]
  knowledge: string[]
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
}

// Mirrors McpServerIn/McpServerOut in schemas.py.
export interface McpServer {
  name: string
  command: string
  args: string[]
}
