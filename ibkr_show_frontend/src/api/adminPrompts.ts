import { request } from './http'
import type {
  PromptActivatePayload,
  PromptCreateVersionPayload,
  PromptDetailResponse,
  PromptListItem,
  PromptListResponse,
  PromptMutationResponse,
  PromptRuntimeResponse,
  PromptSyncCodeDefaultsResponse,
} from '@/types/adminPrompts'

export async function fetchAdminPrompts(): Promise<PromptListItem[]> {
  const response = await request<PromptListResponse>('/api/admin/prompts')
  return response.items
}

export function fetchAdminPromptDetail(promptKey: string): Promise<PromptDetailResponse> {
  return request<PromptDetailResponse>(`/api/admin/prompts/${encodeURIComponent(promptKey)}`)
}

export function createAdminPromptVersion(promptKey: string, payload: PromptCreateVersionPayload): Promise<PromptMutationResponse> {
  return request<PromptMutationResponse>(`/api/admin/prompts/${encodeURIComponent(promptKey)}/versions`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function activateAdminPromptVersion(
  promptKey: string,
  version: string,
  payload: PromptActivatePayload = {},
): Promise<PromptMutationResponse> {
  return request<PromptMutationResponse>(`/api/admin/prompts/${encodeURIComponent(promptKey)}/versions/${encodeURIComponent(version)}/activate`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function seedDefaultAdminPrompts(): Promise<PromptMutationResponse> {
  return request<PromptMutationResponse>('/api/admin/prompts/seed-defaults', {
    method: 'POST',
  })
}

export function createAdminPromptVersionFromCodeDefault(promptKey: string): Promise<PromptMutationResponse> {
  return request<PromptMutationResponse>(`/api/admin/prompts/${encodeURIComponent(promptKey)}/versions/from-code-default`, {
    method: 'POST',
  })
}

export function syncCodeDefaultAdminPrompts(): Promise<PromptSyncCodeDefaultsResponse> {
  return request<PromptSyncCodeDefaultsResponse>('/api/admin/prompts/sync-code-defaults', {
    method: 'POST',
  })
}

export function fetchAdminRuntimePrompt(promptKey: string): Promise<PromptRuntimeResponse> {
  return request<PromptRuntimeResponse>(`/api/admin/prompts/${encodeURIComponent(promptKey)}/runtime`)
}
