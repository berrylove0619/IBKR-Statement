import { request } from './http'
import type {
  LongbridgeMcpTestResponse,
  LongbridgeOpenApiHealth,
  LongbridgeOpenApiMutationResponse,
  LongbridgeOpenApiOauthCompletePayload,
  LongbridgeOpenApiOauthStartPayload,
  LongbridgeOpenApiOauthStartResponse,
  LongbridgeOpenApiStatus,
  LongbridgeUnifiedOAuthMutationResponse,
  LongbridgeUnifiedOAuthStatus,
} from '@/types/adminLongbridgeMcp'

export function fetchLongbridgeUnifiedStatus(): Promise<LongbridgeUnifiedOAuthStatus> {
  return request<LongbridgeUnifiedOAuthStatus>('/api/admin/longbridge/oauth/status')
}

export function fetchLongbridgeUnifiedHealth(): Promise<LongbridgeUnifiedOAuthStatus> {
  return request<LongbridgeUnifiedOAuthStatus>('/api/admin/longbridge/oauth/health')
}

export function refreshLongbridgeUnifiedOauth(): Promise<LongbridgeUnifiedOAuthMutationResponse> {
  return request<LongbridgeUnifiedOAuthMutationResponse>('/api/admin/longbridge/oauth/refresh', {
    method: 'POST',
  })
}

export function testLongbridgeMcp(): Promise<LongbridgeMcpTestResponse> {
  return request<LongbridgeMcpTestResponse>('/api/admin/longbridge-mcp/test', {
    method: 'POST',
  })
}

export function fetchLongbridgeOpenApiStatus(): Promise<LongbridgeOpenApiStatus> {
  return request<LongbridgeOpenApiStatus>('/api/admin/longbridge/openapi/oauth/status')
}

export function startLongbridgeOpenApiOauth(payload: LongbridgeOpenApiOauthStartPayload): Promise<LongbridgeOpenApiOauthStartResponse> {
  return request<LongbridgeOpenApiOauthStartResponse>('/api/admin/longbridge/openapi/oauth/start', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function completeLongbridgeOpenApiOauth(payload: LongbridgeOpenApiOauthCompletePayload): Promise<LongbridgeOpenApiMutationResponse> {
  return request<LongbridgeOpenApiMutationResponse>('/api/admin/longbridge/openapi/oauth/complete', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function refreshLongbridgeOpenApiOauth(): Promise<LongbridgeOpenApiMutationResponse> {
  return request<LongbridgeOpenApiMutationResponse>('/api/admin/longbridge/openapi/oauth/refresh', {
    method: 'POST',
  })
}

export function disconnectLongbridgeOpenApiOauth(): Promise<LongbridgeOpenApiMutationResponse> {
  return request<LongbridgeOpenApiMutationResponse>('/api/admin/longbridge/openapi/oauth/disconnect', {
    method: 'POST',
  })
}

export function fetchLongbridgeOpenApiHealth(): Promise<LongbridgeOpenApiHealth> {
  return request<LongbridgeOpenApiHealth>('/api/admin/longbridge/openapi/health')
}
