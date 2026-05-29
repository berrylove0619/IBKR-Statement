export type AgentTaskStatus = 'queued' | 'running' | 'completed' | 'failed'
export type AgentGraphNodeStatus = 'pending' | 'running' | 'success' | 'failed' | 'fallback' | 'skipped'

export interface AgentGraphNode {
  id: string
  label: string
  status: AgentGraphNodeStatus
  started_at: string | null
  finished_at: string | null
  elapsed_ms: number
  fallback_used: boolean
  fallback_reason: string | null
  error: string | null
  rounds_used: number
  tools_called: string[]
  tool_calls: Array<{
    tool_name: string
    mcp_tool_name?: string | null
    success?: boolean | null
    empty_result?: boolean | null
    error_type?: string | null
  }>
  tool_call_count: number
  data_limitations_count: number
}

export interface AgentGraphEdge {
  source: string
  target: string
}

export interface AgentGraphSnapshot {
  graph_version: string
  nodes: AgentGraphNode[]
  edges: AgentGraphEdge[]
  current_nodes: string[]
  status: AgentGraphNodeStatus
  updated_seq: number
  started_at: string | null
  updated_at: string | null
}

export interface AgentGraphProgressSummary {
  status?: string
  total_nodes?: number
  completed_nodes?: number
  running_nodes?: number
  failed_nodes?: number
  fallback_nodes?: number
  elapsed_ms?: number
  tool_call_count?: number
}

export interface AgentTaskGraphResponse {
  task_id: string
  status: AgentTaskStatus
  updated_seq: number
  graph_snapshot: AgentGraphSnapshot | null
  graph_progress_summary: AgentGraphProgressSummary
}

export interface AgentTaskGraphEvent {
  seq: number
  type: string
  created_at: string
  node_id?: string
  status?: AgentGraphNodeStatus
  started_at?: string | null
  finished_at?: string | null
  elapsed_ms?: number
  fallback_used?: boolean
  fallback_reason?: string | null
  error?: string | null
  rounds_used?: number
  tools_called?: string[]
  tool_calls?: AgentGraphNode['tool_calls']
  tool_call_count?: number
  data_limitations_count?: number
}

export interface AgentTask {
  id: string
  agent: string
  task_type: string
  label: string
  status: AgentTaskStatus
  payload: Record<string, unknown>
  result_id: string | null
  error_code: string | null
  error_message: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  updated_at: string
  updated_seq: number
  graph_snapshot: AgentGraphSnapshot | null
  graph_progress_summary: AgentGraphProgressSummary
  graph_events: AgentTaskGraphEvent[]
}

export interface AgentTaskListResponse {
  items: AgentTask[]
}
