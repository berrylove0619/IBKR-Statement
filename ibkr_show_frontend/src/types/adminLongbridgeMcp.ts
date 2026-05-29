export type LongbridgeUnifiedOAuthStatus = {
  auth_mode: 'unified_openapi_oauth'
  token_source: 'openapi_oauth_store'
  unified_oauth_enabled: boolean
  openapi_connected: boolean
  mcp_effective_connected: boolean
  client_id_masked: string
  has_access_token: boolean
  has_refresh_token: boolean
  refresh_available: boolean
  expires_at: number | null
  expires_in_seconds: number | null
  mcp_endpoint: string
  openapi_sdk_connected: boolean
  message: string
}

export type LongbridgeUnifiedOAuthMutationResponse = {
  success: boolean
  message: string
  status: LongbridgeUnifiedOAuthStatus
}

export type LongbridgeMcpTestResponse = {
  success: boolean
  message: string
  tool_count: number | null
  quote_sample: Record<string, unknown> | null
  error_code: string | null
  data_limitations: string[]
}

export type LongbridgeOpenApiStatus = {
  enabled: boolean
  configured: boolean
  oauth_connected: boolean
  client_id_configured: boolean
  client_id: string
  has_access_token: boolean
  access_token_masked: string
  has_refresh_token: boolean
  refresh_token_masked: string
  scope: string
  expires_at: number | null
  expires_in_seconds: number | null
  auto_refresh_enabled: boolean
  refresh_available: boolean
  refresh_skew_seconds: number
  pending_authorizations: number
  last_error: string
  config_file: string
  sdk_token_cache_file: string
  auto_registered?: boolean
  registration_client_uri?: string
  message: string
}

export type LongbridgeOpenApiOauthStartPayload = {
  redirect_uri?: string
  scope?: string
}

export type LongbridgeOpenApiOauthCompletePayload = {
  code: string
  state: string
}

export type LongbridgeOpenApiOauthStartResponse = {
  authorization_url: string
  state: string
  client_id: string
  redirect_uri: string
  scope: string
  expires_at: number
}

export type LongbridgeOpenApiMutationResponse = {
  success: boolean
  message: string
  status: LongbridgeOpenApiStatus | null
}

export type LongbridgeOpenApiHealth = {
  enabled: boolean
  configured: boolean
  sdk_loaded: boolean
  sdk_oauth_supported: boolean
  oauth_connected: boolean
  can_initialize_config: boolean
  message: string
  oauth_status: LongbridgeOpenApiStatus
}
