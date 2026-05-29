import { request } from './http'
import type {
  TradeReviewHealth,
  TradeReviewListResponse,
  TradeReviewMistakeSummaryResponse,
  TradeReviewResult,
} from '@/types/tradeReview'
import type { AgentTask, AgentTaskListResponse } from '@/types/agentTasks'

function toQueryString(params: Record<string, string | number | undefined | null>): string {
  const searchParams = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      searchParams.set(key, String(value))
    }
  })
  const queryString = searchParams.toString()
  return queryString ? `?${queryString}` : ''
}

export function fetchTradeReviewHealth(): Promise<TradeReviewHealth> {
  return request<TradeReviewHealth>('/api/agent/trade-review/health')
}

export function generateSymbolReview(payload: {
  symbol: string
  start_date?: string
  end_date?: string
  force_refresh?: boolean
}): Promise<TradeReviewResult> {
  return request<TradeReviewResult>(`/api/agent/trade-review/symbol/${encodeURIComponent(payload.symbol)}/generate`, {
    method: 'POST',
    body: JSON.stringify({
      start_date: payload.start_date || undefined,
      end_date: payload.end_date || undefined,
      force_refresh: Boolean(payload.force_refresh),
    }),
  })
}

export function startSymbolReviewTask(payload: {
  symbol: string
  start_date?: string
  end_date?: string
  force_refresh?: boolean
}): Promise<AgentTask> {
  return request<AgentTask>(`/api/agent/trade-review/symbol/${encodeURIComponent(payload.symbol)}/tasks`, {
    method: 'POST',
    body: JSON.stringify({
      start_date: payload.start_date || undefined,
      end_date: payload.end_date || undefined,
      force_refresh: Boolean(payload.force_refresh),
    }),
  })
}

export function generateSingleTradeReview(tradeId: string): Promise<TradeReviewResult> {
  return request<TradeReviewResult>(`/api/agent/trade-review/trade/${encodeURIComponent(tradeId)}/generate`, {
    method: 'POST',
    body: JSON.stringify({ force_refresh: false }),
  })
}

export function startSingleTradeReviewTask(tradeId: string): Promise<AgentTask> {
  return request<AgentTask>(`/api/agent/trade-review/trade/${encodeURIComponent(tradeId)}/tasks`, {
    method: 'POST',
    body: JSON.stringify({ force_refresh: false }),
  })
}

export async function fetchTradeReviewTasks(limit = 20): Promise<AgentTask[]> {
  const response = await request<AgentTaskListResponse>(`/api/agent/trade-review/tasks${toQueryString({ limit })}`)
  return response.items
}

export function fetchTradeReviewTask(taskId: string): Promise<AgentTask> {
  return request<AgentTask>(`/api/agent/trade-review/tasks/${encodeURIComponent(taskId)}`)
}

export async function fetchRecentTradeReviews(params: { limit?: number; review_type?: string } = {}): Promise<TradeReviewResult[]> {
  const response = await request<TradeReviewListResponse>(`/api/agent/trade-review/recent${toQueryString(params)}`)
  return response.items
}

export function fetchTradeReviewDetail(reviewId: string): Promise<TradeReviewResult> {
  return request<TradeReviewResult>(`/api/agent/trade-review/${encodeURIComponent(reviewId)}`)
}

export async function fetchMistakeSummary(): Promise<TradeReviewMistakeSummaryResponse> {
  return request<TradeReviewMistakeSummaryResponse>('/api/agent/trade-review/mistakes/summary')
}
