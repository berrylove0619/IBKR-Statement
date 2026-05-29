import { API_BASE_URL, request } from './http'
import type { AgentTaskGraphEvent, AgentTaskGraphResponse } from '@/types/agentTasks'

export function fetchAgentTaskGraph(taskId: string): Promise<AgentTaskGraphResponse> {
  return request<AgentTaskGraphResponse>(`/api/agent/tasks/${encodeURIComponent(taskId)}/graph`)
}

export function buildAgentTaskEventsUrl(taskId: string, afterSeq = 0): string {
  const params = new URLSearchParams({ after_seq: String(afterSeq) })
  return `${API_BASE_URL}/api/agent/tasks/${encodeURIComponent(taskId)}/events?${params.toString()}`
}

export function applyGraphEvent(snapshot: AgentTaskGraphResponse['graph_snapshot'], event: AgentTaskGraphEvent): AgentTaskGraphResponse['graph_snapshot'] {
  if (!snapshot) return snapshot
  const next = {
    ...snapshot,
    nodes: snapshot.nodes.map((node) => ({ ...node })),
    current_nodes: [...snapshot.current_nodes],
    updated_seq: Math.max(snapshot.updated_seq || 0, event.seq || 0),
    updated_at: event.created_at || snapshot.updated_at,
  }
  if (event.type === 'node_started' && event.node_id) {
    next.nodes = next.nodes.map((node) =>
      node.id === event.node_id
        ? { ...node, status: 'running', started_at: node.started_at || event.created_at, finished_at: null, error: null }
        : node,
    )
  }
  if ((event.type === 'node_finished' || event.type === 'node_failed') && event.node_id) {
    next.nodes = next.nodes.map((node) => (node.id === event.node_id ? { ...node, ...compactNodeEvent(event) } : node))
  }
  if (event.type === 'graph_failed') {
    next.status = 'failed'
    next.nodes = next.nodes.map((node) => (node.status === 'running' ? { ...node, status: 'failed', error: event.error || node.error } : node))
  }
  next.current_nodes = next.nodes.filter((node) => node.status === 'running').map((node) => node.id)
  if (next.nodes.some((node) => node.status === 'failed')) next.status = 'failed'
  else if (next.current_nodes.length) next.status = 'running'
  else if (next.nodes.length && next.nodes.every((node) => ['success', 'fallback', 'skipped'].includes(node.status))) next.status = next.nodes.some((node) => node.status === 'fallback') ? 'fallback' : 'success'
  return next
}

function compactNodeEvent(event: AgentTaskGraphEvent) {
  return {
    status: event.status || (event.type === 'node_failed' ? 'failed' : 'success'),
    started_at: event.started_at ?? null,
    finished_at: event.finished_at ?? event.created_at ?? null,
    elapsed_ms: event.elapsed_ms ?? 0,
    fallback_used: Boolean(event.fallback_used),
    fallback_reason: event.fallback_reason ?? null,
    error: event.error ?? null,
    rounds_used: event.rounds_used ?? 0,
    tools_called: event.tools_called ?? [],
    tool_calls: event.tool_calls ?? [],
    tool_call_count: event.tool_call_count ?? 0,
    data_limitations_count: event.data_limitations_count ?? 0,
  }
}
