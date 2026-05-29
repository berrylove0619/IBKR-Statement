from pydantic import BaseModel


class LongbridgeOpenAPIOAuthStatusResponse(BaseModel):
    enabled: bool
    configured: bool
    oauth_connected: bool
    client_id_configured: bool
    client_id: str = ""
    has_access_token: bool
    access_token_masked: str = ""
    has_refresh_token: bool
    refresh_token_masked: str = ""
    scope: str = ""
    expires_at: int | None = None
    expires_in_seconds: int | None = None
    auto_refresh_enabled: bool = True
    refresh_available: bool
    refresh_skew_seconds: int = 300
    pending_authorizations: int = 0
    last_error: str = ""
    config_file: str
    sdk_token_cache_file: str = ""
    auto_registered: bool = False
    registration_client_uri: str = ""
    message: str = ""


class LongbridgeOpenAPIOAuthStartRequest(BaseModel):
    redirect_uri: str | None = None
    scope: str | None = None


class LongbridgeOpenAPIOAuthCompleteRequest(BaseModel):
    code: str
    state: str


class LongbridgeOpenAPIOAuthStartResponse(BaseModel):
    authorization_url: str
    state: str
    client_id: str
    redirect_uri: str
    scope: str = ""
    expires_at: int


class LongbridgeOpenAPIOAuthMutationResponse(BaseModel):
    success: bool
    message: str
    status: LongbridgeOpenAPIOAuthStatusResponse | None = None


class LongbridgeOpenAPIHealthResponse(BaseModel):
    enabled: bool
    configured: bool
    sdk_loaded: bool
    sdk_oauth_supported: bool
    oauth_connected: bool
    can_initialize_config: bool
    message: str
    oauth_status: LongbridgeOpenAPIOAuthStatusResponse
