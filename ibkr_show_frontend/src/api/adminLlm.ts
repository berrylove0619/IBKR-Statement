import { request } from './http'
import type {
  LlmChatTestResponse,
  LlmHealth,
  LlmProvider,
  LlmProviderListResponse,
  LlmProviderMutationResponse,
  LlmProviderPayload,
  LlmProviderTestResponse,
} from '@/types/adminLlm'

export function fetchLlmHealth(): Promise<LlmHealth> {
  return request<LlmHealth>('/api/admin/llm/health')
}

export async function fetchLlmProviders(): Promise<LlmProvider[]> {
  const response = await request<LlmProviderListResponse>('/api/admin/llm/providers')
  return response.items
}

export function createLlmProvider(payload: LlmProviderPayload): Promise<LlmProviderMutationResponse> {
  return request<LlmProviderMutationResponse>('/api/admin/llm/providers', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updateLlmProvider(id: string, payload: Partial<LlmProviderPayload>): Promise<LlmProviderMutationResponse> {
  return request<LlmProviderMutationResponse>(`/api/admin/llm/providers/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function deleteLlmProvider(id: string): Promise<LlmProviderMutationResponse> {
  return request<LlmProviderMutationResponse>(`/api/admin/llm/providers/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
}

export function activateLlmProvider(id: string): Promise<LlmProviderMutationResponse> {
  return request<LlmProviderMutationResponse>(`/api/admin/llm/providers/${encodeURIComponent(id)}/activate`, {
    method: 'POST',
  })
}

export function testLlmProvider(id: string, prompt: string): Promise<LlmProviderTestResponse> {
  return request<LlmProviderTestResponse>(`/api/admin/llm/providers/${encodeURIComponent(id)}/test`, {
    method: 'POST',
    body: JSON.stringify({ prompt }),
  })
}

export function testActiveLlmChat(message: string, model: string): Promise<LlmChatTestResponse> {
  return request<LlmChatTestResponse>('/api/admin/llm/chat-test', {
    method: 'POST',
    body: JSON.stringify({ message, model: model || undefined }),
  })
}
