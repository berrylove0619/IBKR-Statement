from typing import Literal

from pydantic import BaseModel, Field


class PromptDefinition(BaseModel):
    prompt_key: str
    display_name: str
    module_name: str
    agent_name: str
    description: str
    default_content: str


class PromptVersionPublic(BaseModel):
    id: str
    prompt_key: str
    display_name: str
    module_name: str
    agent_name: str
    description: str
    content: str
    version: str
    status: Literal["draft", "active", "archived"]
    content_hash: str
    is_default: bool
    created_at: str
    updated_at: str
    created_by: str | None = None
    activated_at: str | None = None
    change_note: str | None = None


class PromptListItem(BaseModel):
    prompt_key: str
    display_name: str
    module_name: str
    agent_name: str
    description: str
    active_version: str | None = None
    active_content_hash: str | None = None
    active_updated_at: str | None = None
    has_active: bool
    is_default_active: bool = False
    code_default_hash: str | None = None
    matches_code_default: bool = False
    is_code_default_outdated: bool = False


class PromptCreateVersionRequest(BaseModel):
    content: str = Field(min_length=1)
    change_note: str | None = None


class PromptActivateRequest(BaseModel):
    change_note: str | None = None


class PromptRuntimeMetadata(BaseModel):
    prompt_key: str
    version: str | None = None
    content_hash: str | None = None
    source: str


class PromptRuntimeResponse(BaseModel):
    content: str
    metadata: PromptRuntimeMetadata


class PromptDetailResponse(BaseModel):
    definition: PromptDefinition
    versions: list[PromptVersionPublic]
    active: PromptVersionPublic | None = None


class PromptListResponse(BaseModel):
    items: list[PromptListItem]


class PromptMutationResponse(BaseModel):
    prompt: PromptVersionPublic | None = None
    message: str


class PromptSyncCodeDefaultItem(BaseModel):
    prompt_key: str
    created: bool
    skipped: bool
    message: str
    prompt: PromptVersionPublic | None = None


class PromptSyncCodeDefaultsResponse(BaseModel):
    created: list[PromptSyncCodeDefaultItem]
    skipped: list[PromptSyncCodeDefaultItem]
    message: str
