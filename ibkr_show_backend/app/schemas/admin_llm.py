from pydantic import BaseModel, Field


class LLMProviderPublic(BaseModel):
    id: str
    name: str
    provider_type: str
    base_url: str
    default_model: str
    available_models: list[str] = Field(default_factory=list)
    api_key_masked: str
    is_active: bool
    enabled: bool
    enable_thinking: bool = False
    reasoning_effort: str = "high"
    timeout_seconds: int
    temperature: float
    context_window_tokens: int
    input_token_limit: int
    output_token_limit: int
    created_at: str
    updated_at: str


class LLMHealthResponse(BaseModel):
    enabled: bool
    has_active_provider: bool
    active_provider: LLMProviderPublic | None = None


class LLMProviderListResponse(BaseModel):
    items: list[LLMProviderPublic]


class LLMProviderCreateRequest(BaseModel):
    name: str
    provider_type: str = "openai_compatible"
    base_url: str
    api_key: str
    default_model: str
    available_models: list[str] = Field(default_factory=list)
    enabled: bool = True
    enable_thinking: bool = False
    reasoning_effort: str = "high"
    timeout_seconds: int = 60
    temperature: float = 0.2
    context_window_tokens: int = 200000
    input_token_limit: int = 150000
    output_token_limit: int = 10000
    max_tokens: int | None = None


class LLMProviderUpdateRequest(BaseModel):
    name: str | None = None
    provider_type: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    default_model: str | None = None
    available_models: list[str] | None = None
    enabled: bool | None = None
    enable_thinking: bool | None = None
    reasoning_effort: str | None = None
    timeout_seconds: int | None = None
    temperature: float | None = None
    context_window_tokens: int | None = None
    input_token_limit: int | None = None
    output_token_limit: int | None = None
    max_tokens: int | None = None


class LLMProviderMutationResponse(BaseModel):
    provider: LLMProviderPublic | None = None
    message: str


class LLMProviderTestRequest(BaseModel):
    prompt: str | None = None


class LLMProviderTestResponse(BaseModel):
    success: bool
    provider_id: str
    model: str
    latency_ms: int | None = None
    content: str | None = None
    error_code: str | None = None
    message: str | None = None


class LLMChatTestRequest(BaseModel):
    message: str
    model: str | None = None


class LLMChatTestResponse(BaseModel):
    success: bool
    provider_id: str | None = None
    model: str | None = None
    content: str | None = None
    error_code: str | None = None
    message: str | None = None
