/**
 * Agent Evidence Types
 * P1: versioned metadata, evidence_summary, run_trace_summary for all agents.
 * No raw_llm_response or complete evidence_pack exposure to frontend.
 */

export interface AgentMetadata {
  agent_version: string
  prompt_version: string
  schema_version: string
  toolset_version: string
  evidence_schema_version: string
  evidence_builder_version: string
  context_budget_version: string
  invariant_version: string
  harness_version: string
  agent_mode: string
  model_provider_snapshot: AgentModelProviderSnapshot
  generated_at: string
}

export interface AgentModelProviderSnapshot {
  provider_name?: string
  base_url?: string
  model?: string
}

export interface RunTraceTool {
  tool: string
  ok: boolean
  summary: string
  truncated: boolean
  original_size: number | null
  final_size: number | null
}

export interface RunTraceSummary {
  tool_call_count: number
  tool_success_count: number
  tool_error_count: number
  llm_rounds: number
  truncated_observations: number
  tools: RunTraceTool[]
  llm_started: number | null
  llm_finished: number | null
}

export interface EvidenceSection {
  section: string
  source: string
  status: 'available' | 'missing' | 'partial'
  summary: string
  item_count: number
  freshness: string | null
  budget_truncated: boolean
  dropped_items: Record<string, unknown>
  limitations: string[]
}

export interface LLMInputPolicy {
  account_data_policy: string
  public_data_policy: string
  raw_sensitive_data_exposed: boolean
}

export interface BudgetSummary {
  total_original_size: number
  total_final_size: number
  truncated_sections: string[]
  dropped_items: Record<string, unknown>
}

export interface EvidenceSummary {
  data_sources: Record<string, string>
  evidence_sections: EvidenceSection[]
  tools_used: RunTraceTool[]
  missing_data: string[]
  data_limitations: string[]
  budget_summary: BudgetSummary
  llm_input_policy: LLMInputPolicy
}