from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_llm_service, require_admin_session
from app.core.auth import AuthSession
from app.schemas.admin_llm import (
    LLMChatTestRequest,
    LLMChatTestResponse,
    LLMHealthResponse,
    LLMProviderCreateRequest,
    LLMProviderListResponse,
    LLMProviderMutationResponse,
    LLMProviderTestRequest,
    LLMProviderTestResponse,
    LLMProviderUpdateRequest,
)
from app.services.llm_service import LLMClientError, LLMConfigError, LLMProviderNotFoundError, LLMService

router = APIRouter(prefix="/admin/llm", tags=["admin-llm"])


def _handle_config_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LLMProviderNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get("/health", response_model=LLMHealthResponse)
def get_llm_health(
    _auth_session: AuthSession = Depends(require_admin_session),
    service: LLMService = Depends(get_llm_service),
) -> LLMHealthResponse:
    try:
        return LLMHealthResponse(**service.health())
    except LLMConfigError as exc:
        raise _handle_config_error(exc) from exc


@router.get("/providers", response_model=LLMProviderListResponse)
def list_llm_providers(
    _auth_session: AuthSession = Depends(require_admin_session),
    service: LLMService = Depends(get_llm_service),
) -> LLMProviderListResponse:
    try:
        return LLMProviderListResponse(items=service.list_providers(mask_api_key=True))
    except LLMConfigError as exc:
        raise _handle_config_error(exc) from exc


@router.post("/providers", response_model=LLMProviderMutationResponse)
def create_llm_provider(
    payload: LLMProviderCreateRequest,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: LLMService = Depends(get_llm_service),
) -> LLMProviderMutationResponse:
    try:
        provider = service.create_provider(payload)
        return LLMProviderMutationResponse(provider=provider, message="Provider created")
    except LLMConfigError as exc:
        raise _handle_config_error(exc) from exc


@router.put("/providers/{provider_id}", response_model=LLMProviderMutationResponse)
def update_llm_provider(
    provider_id: str,
    payload: LLMProviderUpdateRequest,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: LLMService = Depends(get_llm_service),
) -> LLMProviderMutationResponse:
    try:
        provider = service.update_provider(provider_id, payload)
        return LLMProviderMutationResponse(provider=provider, message="Provider updated")
    except (LLMConfigError, LLMProviderNotFoundError) as exc:
        raise _handle_config_error(exc) from exc


@router.delete("/providers/{provider_id}", response_model=LLMProviderMutationResponse)
def delete_llm_provider(
    provider_id: str,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: LLMService = Depends(get_llm_service),
) -> LLMProviderMutationResponse:
    try:
        provider, message = service.delete_provider(provider_id)
        return LLMProviderMutationResponse(provider=provider, message=message)
    except LLMProviderNotFoundError as exc:
        raise _handle_config_error(exc) from exc


@router.post("/providers/{provider_id}/activate", response_model=LLMProviderMutationResponse)
def activate_llm_provider(
    provider_id: str,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: LLMService = Depends(get_llm_service),
) -> LLMProviderMutationResponse:
    try:
        provider = service.set_active_provider(provider_id)
        return LLMProviderMutationResponse(provider=provider, message="Provider activated")
    except (LLMConfigError, LLMProviderNotFoundError) as exc:
        raise _handle_config_error(exc) from exc


@router.post("/providers/{provider_id}/test", response_model=LLMProviderTestResponse)
def test_llm_provider(
    provider_id: str,
    payload: LLMProviderTestRequest | None = None,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: LLMService = Depends(get_llm_service),
) -> LLMProviderTestResponse:
    try:
        result = service.test_provider(provider_id, prompt=payload.prompt if payload else None)
        return LLMProviderTestResponse(**result)
    except (LLMConfigError, LLMProviderNotFoundError) as exc:
        raise _handle_config_error(exc) from exc


@router.post("/chat-test", response_model=LLMChatTestResponse)
def test_active_llm_chat(
    payload: LLMChatTestRequest,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: LLMService = Depends(get_llm_service),
) -> LLMChatTestResponse:
    try:
        active_provider = service.get_active_provider()
        if active_provider is None:
            raise LLMConfigError("No active LLM provider is configured")
        content = service.chat(
            [
                {"role": "system", "content": "You are a concise assistant."},
                {"role": "user", "content": payload.message},
            ],
            provider_id=active_provider.id,
            model=payload.model,
        )
        return LLMChatTestResponse(
            success=True,
            provider_id=active_provider.id,
            model=payload.model or active_provider.default_model,
            content=content,
        )
    except LLMClientError as exc:
        return LLMChatTestResponse(success=False, error_code=exc.error_code, message=exc.message)
    except LLMConfigError as exc:
        raise _handle_config_error(exc) from exc
