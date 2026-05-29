import { request } from '@/api/http'

export interface SymbolSuggestion {
  symbol: string
  distance: number
  similarity: number
}

export interface SymbolCorrection {
  symbol: string
  source: 'fuzzy' | 'llm'
  reason: string
}

export interface SymbolSuggestResponse {
  suggestions: SymbolSuggestion[]
  corrected: SymbolCorrection | null
}

export function fetchSymbolSuggestions(q: string): Promise<SymbolSuggestResponse> {
  return request<SymbolSuggestResponse>(`/api/symbols/suggest?q=${encodeURIComponent(q)}`)
}
