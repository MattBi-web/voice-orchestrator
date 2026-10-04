import type { Agent, AgentInput, AgentUpdateInput, TestRouteResult } from './types'

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
  listTools: () => request<{ tools: string[] }>('/api/tools'),
  testRoute: (utterance: string, startAgentId: string | null, channel: string) =>
    request<TestRouteResult>('/api/test/route', {
      method: 'POST',
      body: JSON.stringify({ utterance, start_agent_id: startAgentId, channel }),
    }),
}
