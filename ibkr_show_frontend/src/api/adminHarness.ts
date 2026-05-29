import { request } from './http'
import type {
  AgentReplaySnapshot,
  AgentReplaysListParams,
  AgentRunsListParams,
  AgentRunTraceDetail,
  AgentRunTraceListItem,
  EvalCase,
  EvalCasesListParams,
  EvalRun,
  EvalRunPayload,
  EvalRunsListParams,
  HarnessListResponse,
  LLMCallMetric,
  LlmCallListParams,
} from '@/types/adminHarness'

function queryString(params: object): string {
  const search = new URLSearchParams()
  Object.entries(params as Record<string, unknown>).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    search.set(key, String(value))
  })
  const text = search.toString()
  return text ? `?${text}` : ''
}

export function listLlmCalls(params: LlmCallListParams = {}): Promise<HarnessListResponse<LLMCallMetric>> {
  return request<HarnessListResponse<LLMCallMetric>>(`/api/admin/llm-calls${queryString(params)}`)
}

export function listAgentRuns(params: AgentRunsListParams = {}): Promise<HarnessListResponse<AgentRunTraceListItem>> {
  return request<HarnessListResponse<AgentRunTraceListItem>>(`/api/admin/agent-runs${queryString(params)}`)
}

export function getAgentRun(runId: string): Promise<AgentRunTraceDetail> {
  return request<AgentRunTraceDetail>(`/api/admin/agent-runs/${encodeURIComponent(runId)}`)
}

export function listAgentReplays(params: AgentReplaysListParams = {}): Promise<HarnessListResponse<AgentReplaySnapshot>> {
  return request<HarnessListResponse<AgentReplaySnapshot>>(`/api/admin/agent-replays${queryString(params)}`)
}

export function getAgentReplay(replayId: string): Promise<AgentReplaySnapshot> {
  return request<AgentReplaySnapshot>(`/api/admin/agent-replays/${encodeURIComponent(replayId)}`)
}

export function getAgentReplayByRun(runId: string): Promise<AgentReplaySnapshot> {
  return request<AgentReplaySnapshot>(`/api/admin/agent-replays/by-run/${encodeURIComponent(runId)}`)
}

export function exportAgentReplay(replayId: string): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(`/api/admin/agent-replays/${encodeURIComponent(replayId)}/export`)
}

export function listEvalCases(params: EvalCasesListParams = {}): Promise<HarnessListResponse<EvalCase>> {
  return request<HarnessListResponse<EvalCase>>(`/api/admin/agent-eval/cases${queryString(params)}`)
}

export function getEvalCase(caseId: string): Promise<EvalCase> {
  return request<EvalCase>(`/api/admin/agent-eval/cases/${encodeURIComponent(caseId)}`)
}

export function seedEvalCases(force = false): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(`/api/admin/agent-eval/cases/seed${queryString({ force })}`, {
    method: 'POST',
  })
}

export function createEvalCaseFromReplay(replayId: string, save = true): Promise<EvalCase> {
  return request<EvalCase>(`/api/admin/agent-eval/cases/from-replay/${encodeURIComponent(replayId)}${queryString({ save })}`, {
    method: 'POST',
  })
}

export function runEval(payload: EvalRunPayload): Promise<EvalRun> {
  return request<EvalRun>('/api/admin/agent-eval/runs', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function listEvalRuns(params: EvalRunsListParams = {}): Promise<HarnessListResponse<EvalRun>> {
  return request<HarnessListResponse<EvalRun>>(`/api/admin/agent-eval/runs${queryString(params)}`)
}

export function getEvalRun(evalRunId: string): Promise<EvalRun> {
  return request<EvalRun>(`/api/admin/agent-eval/runs/${encodeURIComponent(evalRunId)}`)
}
