from pydantic import BaseModel


class IBKRFlexSettingsResponse(BaseModel):
    query_id: str
    flex_token_masked: str
    has_flex_token: bool
    config_file: str


class IBKRFlexSettingsUpdateRequest(BaseModel):
    query_id: str | None = None
    flex_token: str | None = None


class IBKRFlexSettingsMutationResponse(BaseModel):
    settings: IBKRFlexSettingsResponse
    message: str


class IBKRFlexTestResponse(BaseModel):
    success: bool
    query_id: str
    reference_code: str | None = None
    message: str | None = None


class IBKRImportResponse(BaseModel):
    success: bool
    filename: str
    result: dict
    message: str

