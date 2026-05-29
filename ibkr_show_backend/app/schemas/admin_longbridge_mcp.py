from pydantic import BaseModel, Field


class LongbridgeUnifiedOAuthStatusResponse(BaseModel):
    auth_mode: str = "unified_openapi_oauth"
    token_source: str = "openapi_oauth_store"
    unified_oauth_enabled: bool = True
    openapi_connected: bool
    mcp_effective_connected: bool
    client_id_masked: str = ""
    has_access_token: bool
    has_refresh_token: bool
    refresh_available: bool
    expires_at: int | None = None
    expires_in_seconds: int | None = None
    mcp_endpoint: str = ""
    openapi_sdk_connected: bool
    auto_registered: bool = False
    registration_client_uri: str = ""
    message: str


class LongbridgeUnifiedOAuthMutationResponse(BaseModel):
    success: bool
    message: str
    status: LongbridgeUnifiedOAuthStatusResponse


class LongbridgeMCPTestResponse(BaseModel):
    success: bool
    message: str
    tool_count: int | None = None
    quote_sample: dict | None = None
    error_code: str | None = None
    data_limitations: list[str] = Field(default_factory=list)
