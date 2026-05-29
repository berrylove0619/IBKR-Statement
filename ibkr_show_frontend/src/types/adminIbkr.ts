export type IbkrFlexSettings = {
  query_id: string
  flex_token_masked: string
  has_flex_token: boolean
  config_file: string
}

export type IbkrFlexSettingsPayload = {
  query_id?: string
  flex_token?: string
}

export type IbkrFlexSettingsMutationResponse = {
  settings: IbkrFlexSettings
  message: string
}

export type IbkrFlexTestResponse = {
  success: boolean
  query_id: string
  reference_code: string | null
  message: string | null
}

export type IbkrImportIndexResult = {
  index: string
  upserted: number
}

export type IbkrImportResponse = {
  success: boolean
  filename: string
  result: Record<string, IbkrImportIndexResult>
  message: string
}

