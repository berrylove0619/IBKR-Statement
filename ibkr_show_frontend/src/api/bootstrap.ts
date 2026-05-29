import { request } from './http'
import type { BootstrapInitPayload, BootstrapInitResponse, BootstrapStatus } from '@/types/bootstrap'

export function fetchBootstrapStatus(): Promise<BootstrapStatus> {
  return request<BootstrapStatus>('/api/auth/bootstrap/status')
}

export function initializeBootstrap(payload: BootstrapInitPayload): Promise<BootstrapInitResponse> {
  return request<BootstrapInitResponse>('/api/auth/bootstrap/init', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}
