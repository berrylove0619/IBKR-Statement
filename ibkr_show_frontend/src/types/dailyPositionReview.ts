import type { AgentRunTraceItem } from './tradeDecision'

export interface DailyPositionReviewHealth {
  enabled: boolean
  llm_configured: boolean
  longbridge_configured: boolean
  account_data_source: string
  public_market_data_source: string
  message: string
}

export interface DailyPositionReviewPositionItem {
  symbol: string
  normalized_symbol: string
  name: string | null
  asset_class: string | null
  sub_category: string | null
  quantity: number | null
  mark_price: number | null
  market_value: number | null
  weight: number | null
  daily_change_percent: number | null
  daily_pnl: number | null
  contribution_ratio: number | null
  average_cost: number | null
  cost_basis: number | null
  unrealized_pnl: number | null
  unrealized_pnl_percent: number | null
  is_major_contributor: boolean
  is_major_drag: boolean
  data_source: string
}

export interface DailyPositionReviewContext {
  report_date: string
  data_sources: Record<string, string>
  overview: {
    report_date: string
    currency?: string | null
    total_equity?: number | null
    daily_pnl?: number | null
    daily_return_percent?: number | null
    total_position_value?: number | null
    cash?: number | null
    cash_ratio?: number | null
    position_count: number
    top_contributors: DailyPositionReviewPositionItem[]
    top_drags: DailyPositionReviewPositionItem[]
    summary: string
    ibkr_pnl_breakdown: Record<string, number | null>
  }
  positions: DailyPositionReviewPositionItem[]
  rankings: Record<string, DailyPositionReviewPositionItem[]>
  risk: {
    max_position?: DailyPositionReviewPositionItem | null
    max_single_position_weight?: number | null
    top3_weight?: number | null
    top5_weight?: number | null
    theme_buckets: Array<Record<string, unknown>>
    semiconductor_ai_tech_weight?: number | null
    cash_ratio?: number | null
    max_position_down_5pct_account_impact_percent?: number | null
    risk_flags: string[]
    account_posture?: string | null
  }
  benchmarks: {
    items: Array<{
      symbol: string
      return_percent: number | null
      account_excess_return_percent: number | null
      source: string
    }>
    beta_alpha_note: string
  }
  focus_symbols: string[]
  attribution_quality: Record<string, unknown>
  data_quality: {
    missing_fields?: string[]
    warnings?: string[]
  }
}

export interface DailyPositionReviewResult {
  id: string
  report_date: string
  review_type: string
  summary: string
  account_conclusion: string
  attribution_summary: string
  major_contributors_analysis: Array<Record<string, unknown>>
  major_drags_analysis: Array<Record<string, unknown>>
  focus_symbol_analyses: Array<Record<string, unknown>>
  market_context: string
  risk_analysis: string
  tomorrow_watchlist: Array<Record<string, unknown>>
  operation_observation: string
  data_limitations: string[]
  evidence_used: string[]
  data_source_summary: Record<string, string>
  deterministic_context: Record<string, unknown>
  display_context: Record<string, unknown>
  run_trace: AgentRunTraceItem[]
  metadata: Record<string, unknown>
  evidence_summary: Record<string, unknown>
  run_trace_summary: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface DailyPositionReviewDateListResponse {
  items: string[]
}

export interface DailyPositionReviewListResponse {
  items: DailyPositionReviewResult[]
}
