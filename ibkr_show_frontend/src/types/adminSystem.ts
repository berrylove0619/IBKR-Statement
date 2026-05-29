export type SystemComponentStatusLevel = 'ok' | 'warning' | 'error' | 'disabled' | 'unknown'

export type SystemComponentStatus = {
  name: string
  label: string
  status: SystemComponentStatusLevel
  configured: boolean | null
  message: string
  details: Record<string, unknown>
}

export type AdminSystemStatus = {
  overall_status: 'ok' | 'warning' | 'error'
  generated_at: string
  components: SystemComponentStatus[]
}
