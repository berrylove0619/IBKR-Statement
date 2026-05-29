export interface BootstrapStatus {
  initialized: boolean
  auth_source: 'file' | 'env'
}

export interface BootstrapInitPayload {
  username: string
  password: string
}

export interface BootstrapInitResponse {
  initialized: boolean
}
