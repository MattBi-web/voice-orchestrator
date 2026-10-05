import type {
  CallEvent,
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
  KnowledgeDoc,
  KnowledgeDocDetail,
  KnowledgeSearchResult,
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
  // ---- blocco 6: owner login ----
  me: () => request<{ auth_required: boolean; owner: boolean }>('/api/auth/me'),
  login: (password: string) =>
    request<{ auth_required: boolean; owner: boolean }>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ password }),
    }),
  logout: () => request<{ auth_required: boolean; owner: boolean }>('/api/auth/logout', { method: 'POST' }),
  // ---- blocco 5: knowledge base ----
  listKnowledge: () => request<{ documents: KnowledgeDoc[]; max_chunk_chars: number }>('/api/knowledge'),
  getKnowledge: (name: string) => request<KnowledgeDocDetail>(`/api/knowledge/${encodeURIComponent(name)}`),
  addKnowledge: (body: { name: string; content: string; source_type: 'text' | 'file'; overwrite?: boolean }) =>
    request<KnowledgeDoc>('/api/knowledge', { method: 'POST', body: JSON.stringify(body) }),
  addKnowledgeFromUrl: (body: { url: string; name?: string; overwrite?: boolean }) =>
    request<KnowledgeDoc>('/api/knowledge/from-url', { method: 'POST', body: JSON.stringify(body) }),
  deleteKnowledge: (name: string) =>
    request<void>(`/api/knowledge/${encodeURIComponent(name)}`, { method: 'DELETE' }),
  searchKnowledge: (body: { query: string; documents?: string[]; agent_id?: string | null; top_k?: number }) =>
    request<KnowledgeSearchResult>('/api/knowledge/search', { method: 'POST', body: JSON.stringify(body) }),
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
  // ---- blocco 7, fase B: multi-turn text tests ----
  startConversation: (startAgentId: string | null, channel: string, useConfiguredProvider: boolean) =>
    request<{ id: string; greeting: Extract<CallEvent, { type: 'greeting' }> | null; simulated: boolean; provider: string }>(
      '/api/test/conversations',
      {
        method: 'POST',
        body: JSON.stringify({
          start_agent_id: startAgentId,
          channel,
          use_configured_provider: useConfiguredProvider,
        }),
      },
    ),
  conversationTurn: (id: string, utterance: string, slots: Record<string, unknown>) =>
    request<Extract<CallEvent, { type: 'turn' }>>(`/api/test/conversations/${id}/turns`, {
      method: 'POST',
      body: JSON.stringify({ utterance, slots }),
    }),
  endConversation: (id: string) => request<void>(`/api/test/conversations/${id}`, { method: 'DELETE' }),
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
