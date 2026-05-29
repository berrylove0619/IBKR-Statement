export interface LlmProvider {
  id: string
  name: string
  provider_type: string
  base_url: string
  default_model: string
  available_models: string[]
  api_key_masked: string
  is_active: boolean
  enabled: boolean
  enable_thinking: boolean
  reasoning_effort: string
  timeout_seconds: number
  temperature: number
  context_window_tokens: number
  input_token_limit: number
  output_token_limit: number
  created_at: string
  updated_at: string
}

export interface LlmHealth {
  enabled: boolean
  has_active_provider: boolean
  active_provider: LlmProvider | null
}

export interface LlmProviderListResponse {
  items: LlmProvider[]
}

export interface LlmProviderMutationResponse {
  provider: LlmProvider | null
  message: string
}

export interface LlmProviderPayload {
  name: string
  provider_type: string
  base_url: string
  api_key?: string
  default_model: string
  available_models: string[]
  enabled: boolean
  enable_thinking: boolean
  reasoning_effort: string
  timeout_seconds: number
  temperature: number
  context_window_tokens: number
  input_token_limit: number
  output_token_limit: number
}

export interface LlmProviderTestResponse {
  success: boolean
  provider_id: string
  model: string
  latency_ms: number | null
  content: string | null
  error_code: string | null
  message: string | null
}

export interface LlmChatTestResponse {
  success: boolean
  provider_id: string | null
  model: string | null
  content: string | null
  error_code: string | null
  message: string | null
}
