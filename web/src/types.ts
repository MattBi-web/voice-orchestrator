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
