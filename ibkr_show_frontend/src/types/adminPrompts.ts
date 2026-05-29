export type PromptStatus = 'draft' | 'active' | 'archived'
export type PromptRuntimeSource = 'admin_active' | 'code_default' | 'fallback'

export interface PromptDefinition {
  prompt_key: string
  display_name: string
  module_name: string
  agent_name: string
  description: string
  default_content: string
}

export interface PromptVersion {
  id: string
  prompt_key: string
  display_name: string
  module_name: string
  agent_name: string
  description: string
  content: string
  version: string
  status: PromptStatus
  content_hash: string
  is_default: boolean
  created_at: string
  updated_at: string
  created_by: string | null
  activated_at: string | null
  change_note: string | null
}

export interface PromptListItem {
  prompt_key: string
  display_name: string
  module_name: string
  agent_name: string
  description: string
  active_version: string | null
  active_content_hash: string | null
  active_updated_at: string | null
  has_active: boolean
  is_default_active: boolean
  code_default_hash: string | null
  matches_code_default: boolean
  is_code_default_outdated: boolean
}

export interface PromptListResponse {
  items: PromptListItem[]
}

export interface PromptDetailResponse {
  definition: PromptDefinition
  versions: PromptVersion[]
  active: PromptVersion | null
}

export interface PromptRuntimeMetadata {
  prompt_key: string
  version: string | null
  content_hash: string | null
  source: PromptRuntimeSource
  error?: string
}

export interface PromptRuntimeResponse {
  content: string
  metadata: PromptRuntimeMetadata
}

export interface PromptMutationResponse {
  prompt: PromptVersion | null
  message: string
}

export interface PromptSyncCodeDefaultItem {
  prompt_key: string
  created: boolean
  skipped: boolean
  message: string
  prompt: PromptVersion | null
}

export interface PromptSyncCodeDefaultsResponse {
  created: PromptSyncCodeDefaultItem[]
  skipped: PromptSyncCodeDefaultItem[]
  message: string
}

export interface PromptCreateVersionPayload {
  content: string
  change_note?: string
}

export interface PromptActivatePayload {
  change_note?: string
}
