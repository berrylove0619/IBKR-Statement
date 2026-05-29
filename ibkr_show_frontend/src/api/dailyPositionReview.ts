import { request } from './http'
import type { AgentTask, AgentTaskListResponse } from '@/types/agentTasks'
import type {
  DailyPositionReviewContext,
  DailyPositionReviewDateListResponse,
  DailyPositionReviewHealth,
  DailyPositionReviewListResponse,
  DailyPositionReviewResult,
} from '@/types/dailyPositionReview'

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

export function fetchDailyPositionReviewHealth(): Promise<DailyPositionReviewHealth> {
  return request<DailyPositionReviewHealth>('/api/agent/daily-position-review/health')
}

export async function fetchDailyPositionReviewDates(limit = 60): Promise<string[]> {
  const response = await request<DailyPositionReviewDateListResponse>(
    `/api/agent/daily-position-review/dates${toQueryString({ limit })}`,
  )
  return response.items
}

export function fetchDailyPositionReviewContext(reportDate: string): Promise<DailyPositionReviewContext> {
  return request<DailyPositionReviewContext>(`/api/agent/daily-position-review/${encodeURIComponent(reportDate)}/context`)
}

export function fetchDailyPositionReview(reportDate: string): Promise<DailyPositionReviewResult> {
  return request<DailyPositionReviewResult>(`/api/agent/daily-position-review/${encodeURIComponent(reportDate)}`)
}

export async function fetchRecentDailyPositionReviews(limit = 20): Promise<DailyPositionReviewResult[]> {
  const response = await request<DailyPositionReviewListResponse>(
    `/api/agent/daily-position-review/recent${toQueryString({ limit })}`,
  )
  return response.items
}

export function startDailyPositionReviewTask(reportDate: string, forceRefresh = false): Promise<AgentTask> {
  return request<AgentTask>(`/api/agent/daily-position-review/${encodeURIComponent(reportDate)}/tasks`, {
    method: 'POST',
    body: JSON.stringify({ force_refresh: forceRefresh }),
  })
}

export async function fetchDailyPositionReviewTasks(limit = 20): Promise<AgentTask[]> {
  const response = await request<AgentTaskListResponse>(
    `/api/agent/daily-position-review/tasks${toQueryString({ limit })}`,
  )
  return response.items
}
