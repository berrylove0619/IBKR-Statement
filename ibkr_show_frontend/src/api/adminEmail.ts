import { request } from './http'
import type {
  EmailSendLatestResponse,
  EmailSettings,
  EmailSettingsMutationResponse,
  EmailSettingsPayload,
  EmailTestPayload,
  EmailTestResponse,
} from '@/types/adminEmail'

export function fetchEmailSettings(): Promise<EmailSettings> {
  return request<EmailSettings>('/api/admin/email/settings')
}

export function updateEmailSettings(payload: EmailSettingsPayload): Promise<EmailSettingsMutationResponse> {
  return request<EmailSettingsMutationResponse>('/api/admin/email/settings', {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function sendEmailTest(payload: EmailTestPayload = {}): Promise<EmailTestResponse> {
  return request<EmailTestResponse>('/api/admin/email/test', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function sendLatestDailyReview(payload?: { force_refresh?: boolean }): Promise<EmailSendLatestResponse> {
  return request<EmailSendLatestResponse>('/api/admin/email/send-latest-daily-review', {
    method: 'POST',
    body: payload ? JSON.stringify(payload) : undefined,
  })
}

export function sendLatestAccountSnapshot(): Promise<EmailSendLatestResponse> {
  return request<EmailSendLatestResponse>('/api/admin/email/send-latest-account-snapshot', {
    method: 'POST',
  })
}
