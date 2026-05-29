import { request } from './http'
import type {
  IbkrFlexSettings,
  IbkrFlexSettingsMutationResponse,
  IbkrFlexSettingsPayload,
  IbkrFlexTestResponse,
  IbkrImportResponse,
} from '@/types/adminIbkr'

export function fetchIbkrSettings(): Promise<IbkrFlexSettings> {
  return request<IbkrFlexSettings>('/api/admin/ibkr/settings')
}

export function updateIbkrSettings(payload: IbkrFlexSettingsPayload): Promise<IbkrFlexSettingsMutationResponse> {
  return request<IbkrFlexSettingsMutationResponse>('/api/admin/ibkr/settings', {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function testIbkrConnection(): Promise<IbkrFlexTestResponse> {
  return request<IbkrFlexTestResponse>('/api/admin/ibkr/test', {
    method: 'POST',
  })
}

export function pullDailyFromIbkr(): Promise<IbkrImportResponse> {
  return request<IbkrImportResponse>('/api/admin/ibkr/pull-daily', {
    method: 'POST',
  })
}

export function importIbkrHistory(file: File): Promise<IbkrImportResponse> {
  return request<IbkrImportResponse>('/api/admin/ibkr/import-history', {
    method: 'POST',
    headers: {
      'Content-Type': file.type || 'text/csv',
      'X-Filename': encodeURIComponent(file.name),
    },
    body: file,
  })
}

