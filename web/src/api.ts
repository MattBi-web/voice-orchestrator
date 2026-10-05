import type {
  Agent,
  AgentInput,
  AgentLayoutUpdate,
  AgentReparentRequest,
  AgentUpdateInput,
  AnalysisConfig,
  CallAnalysis,
  CallDetail,
  CallRecord,
  CallStats,
  ExportResult,
  McpServer,
  LlmStatus,
  TestRouteResult,
  VoiceStatus,
  VoiceToken,
  WebhookExecution,
  WebhookTool,
} from './types'

// Every function here throws ApiError on a non-2xx response, with the
// backend's own `detail` message (FastAPI's HTTPException shape) attached
// — so a 409 "agent id already exists" or 400 "delete children first"
// reaches the UI as readable text, not a generic "request failed".
export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? detail
    } catch {
      // non-JSON error body — fall back to statusText
    }
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export const api = {
  getTree: () => request<{ root: Agent | null }>('/api/agents'),
  exportAgents: () => request<ExportResult>('/api/agents/export', { method: 'POST' }),
  getAgent: (id: string) => request<Agent>(`/api/agents/${encodeURIComponent(id)}`),
  createAgent: (data: AgentInput) =>
    request<Agent>('/api/agents', { method: 'POST', body: JSON.stringify(data) }),
  updateAgent: (id: string, data: AgentUpdateInput) =>
    request<Agent>(`/api/agents/${encodeURIComponent(id)}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  deleteAgent: (id: string) =>
    request<void>(`/api/agents/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  updateAgentLayout: (id: string, layout: AgentLayoutUpdate) =>
    request<Agent>(`/api/agents/${encodeURIComponent(id)}/layout`, {
      method: 'PATCH',
      body: JSON.stringify(layout),
    }),
  reparentAgent: (id: string, body: AgentReparentRequest) =>
    request<Agent>(`/api/agents/${encodeURIComponent(id)}/parent`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  listTools: () => request<{ tools: string[] }>('/api/tools'),
  testRoute: (utterance: string, startAgentId: string | null, channel: string, useConfiguredProvider = false) =>
    request<TestRouteResult>('/api/test/route', {
      method: 'POST',
      body: JSON.stringify({
        utterance,
        start_agent_id: startAgentId,
        channel,
        use_configured_provider: useConfiguredProvider,
      }),
    }),
  getLlmStatus: () => request<LlmStatus>('/api/llm/status'),
  getVoiceStatus: () => request<VoiceStatus>('/api/voice/status'),
  getVoiceToken: () => request<VoiceToken>('/api/voice/token', { method: 'POST' }),
  getCallStats: (includeTest: boolean, days = 14) =>
    request<CallStats>(`/api/calls/stats?days=${days}&include_test=${includeTest}`),
  // The recent-calls table always shows everything, source column included
  // (test routes are visible, not filtered) — only the tiles/charts above it
  // react to "include test calls".
  getCalls: (limit = 20) => request<{ calls: CallRecord[] }>(`/api/calls?limit=${limit}`),
  listMcpServers: () => request<{ servers: McpServer[] }>('/api/mcp-servers'),
  createMcpServer: (data: McpServer) =>
    request<McpServer>('/api/mcp-servers', { method: 'POST', body: JSON.stringify(data) }),
  updateMcpServer: (name: string, data: McpServer) =>
    request<McpServer>(`/api/mcp-servers/${encodeURIComponent(name)}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  deleteMcpServer: (name: string) =>
    request<void>(`/api/mcp-servers/${encodeURIComponent(name)}`, { method: 'DELETE' }),
  listWebhookTools: () => request<{ tools: WebhookTool[] }>('/api/webhook-tools'),
  createWebhookTool: (data: WebhookTool) =>
    request<WebhookTool>('/api/webhook-tools', { method: 'POST', body: JSON.stringify(data) }),
  updateWebhookTool: (name: string, data: WebhookTool) =>
    request<WebhookTool>(`/api/webhook-tools/${encodeURIComponent(name)}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  deleteWebhookTool: (name: string) =>
    request<void>(`/api/webhook-tools/${encodeURIComponent(name)}`, { method: 'DELETE' }),
  listWebhookExecutions: (limit = 50) =>
    request<{ executions: WebhookExecution[] }>(`/api/webhook-tools/executions?limit=${limit}`),
  getCall: (callId: string) => request<CallDetail>(`/api/calls/${encodeURIComponent(callId)}`),
  analyzeCall: (callId: string) =>
    request<CallAnalysis>(`/api/calls/${encodeURIComponent(callId)}/analyze`, { method: 'POST' }),
  getAnalysisConfig: () => request<AnalysisConfig>('/api/analysis/config'),
  putAnalysisConfig: (cfg: AnalysisConfig) =>
    request<AnalysisConfig>('/api/analysis/config', { method: 'PUT', body: JSON.stringify(cfg) }),
}
