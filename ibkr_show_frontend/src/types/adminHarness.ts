export interface HarnessListResponse<T> {
  items: T[]
  summary?: Record<string, unknown>
}

export interface LLMCallMetric {
  call_id: string
  run_id?: string | null
  session_id?: string | null
  agent_name?: string | null
  node_name?: string | null
  provider_id?: string | null
  provider_name?: string | null
  provider_type?: string | null
  model?: string | null
  call_type?: string | null
  prompt_key?: string | null
  prompt_version?: string | null
  prompt_hash?: string | null
  prompt_source?: string | null
  response_format_type?: string | null
  tool_calling?: boolean
  tool_count?: number
  temperature?: number | null
  max_tokens?: number | null
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens?: number
  reasoning_tokens?: number
  cached_tokens?: number
  latency_ms?: number
  estimated_cost?: number | null
  ok?: boolean
  error_code?: string | null
  error_message?: string | null
  created_at?: string
}

export interface AgentRunTraceListItem {
  run_id: string
  agent_name?: string | null
  agent_version?: string | null
  agent_mode?: string | null
  session_id?: string | null
  user_id?: string | null
  request_id?: string | null
  final_status?: string | null
  error_code?: string | null
  error_message?: string | null
  latency_ms?: number
  started_at?: string
  finished_at?: string | null
  prompt_keys?: string[]
  prompt_versions?: string[]
  prompt_hashes?: string[]
  llm_call_count?: number
  tool_call_count?: number
  total_tokens?: number
  estimated_cost?: number | null
}

export interface AgentRunTraceDetail extends AgentRunTraceListItem {
  prompt_metadata?: Record<string, unknown>
  context_manifest?: Record<string, unknown>
  llm_calls?: Record<string, unknown>[]
  tool_calls?: Record<string, unknown>[]
  validation?: Record<string, unknown>
  repair_attempts?: Record<string, unknown>[]
  fallback?: Record<string, unknown>
  quality_score?: Record<string, unknown>
  node_traces?: Record<string, unknown>[]
  metadata?: Record<string, unknown>
}

export interface AgentReplaySnapshot {
  replay_id: string
  run_id?: string | null
  agent_name?: string | null
  agent_version?: string | null
  agent_mode?: string | null
  created_at?: string
  source?: string
  replay_schema_version?: string
  request?: Record<string, unknown>
  prompt_refs?: Record<string, unknown>[]
  model_config?: Record<string, unknown>
  context_snapshot?: Record<string, unknown>
  tool_snapshots?: Record<string, unknown>[]
  llm_snapshots?: Record<string, unknown>[]
  final_output?: Record<string, unknown>
  persisted_document_id?: string | null
  final_status?: string | null
  data_limitations?: string[]
  trace_ref?: Record<string, unknown>
  metadata?: Record<string, unknown>
}

export interface EvalCase {
  case_id: string
  agent_name?: string | null
  title?: string
  description?: string
  tags?: string[]
  source?: string
  input?: Record<string, unknown>
  mock_context?: Record<string, unknown>
  mock_tool_outputs?: Record<string, unknown>
  expected_behavior?: Record<string, unknown>
  expected_output_fields?: string[]
  forbidden_behavior?: string[]
  scoring_rubric?: Record<string, unknown>
  created_at?: string
  metadata?: Record<string, unknown>
}

export interface EvalCheckResult {
  check_name?: string
  passed?: boolean
  severity?: string
  score?: number
  max_score?: number
  message?: string
  details?: Record<string, unknown>
}

export interface EvalCaseResult {
  case_id?: string
  agent_name?: string | null
  status?: string
  score?: number
  max_score?: number
  checks?: EvalCheckResult[]
  output_summary?: Record<string, unknown>
  error_code?: string | null
  error_message?: string | null
  latency_ms?: number
  replay_id?: string | null
  run_id?: string | null
  metadata?: Record<string, unknown>
}

export interface EvalRun {
  eval_run_id: string
  name?: string
  agent_name?: string | null
  case_ids?: string[]
  config?: Record<string, unknown>
  started_at?: string
  finished_at?: string | null
  status?: string
  summary?: Record<string, unknown>
  results?: EvalCaseResult[]
}

export interface LlmCallListParams {
  hours?: number
  agent_name?: string
  prompt_key?: string
  model?: string
  ok?: boolean | null
  limit?: number
}

export interface AgentRunsListParams {
  hours?: number
  agent_name?: string
  final_status?: string
  limit?: number
}

export interface AgentReplaysListParams {
  hours?: number
  agent_name?: string
  final_status?: string
  limit?: number
}

export interface EvalCasesListParams {
  agent_name?: string
  source?: string
  limit?: number
}

export interface EvalRunsListParams {
  hours?: number
  agent_name?: string
  limit?: number
}

export interface EvalRunPayload {
  case_ids?: string[]
  agent_name?: string | null
  replay_ids?: string[]
  mode?: string
  name?: string | null
}
