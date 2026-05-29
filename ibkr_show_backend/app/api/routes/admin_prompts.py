from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_admin_prompt_service, require_admin_session
from app.core.auth import AuthSession
from app.schemas.admin_prompts import (
    PromptActivateRequest,
    PromptCreateVersionRequest,
    PromptDetailResponse,
    PromptListResponse,
    PromptMutationResponse,
    PromptRuntimeResponse,
    PromptSyncCodeDefaultsResponse,
)
from app.services.admin_prompt_service import (
    AdminPromptService,
    PromptNotFoundError,
    PromptValidationError,
    PromptVersionNotFoundError,
)

router = APIRouter(prefix="/admin/prompts", tags=["admin-prompts"])


def _handle_prompt_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (PromptNotFoundError, PromptVersionNotFoundError)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get("", response_model=PromptListResponse)
def list_prompts(
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AdminPromptService = Depends(get_admin_prompt_service),
) -> PromptListResponse:
    return PromptListResponse(items=service.list_prompts())


@router.post("/seed-defaults", response_model=PromptMutationResponse)
def seed_default_prompts(
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AdminPromptService = Depends(get_admin_prompt_service),
) -> PromptMutationResponse:
    seeded = service.seed_default_versions()
    return PromptMutationResponse(message=f"Ensured {len(seeded)} prompt defaults")


@router.post("/sync-code-defaults", response_model=PromptSyncCodeDefaultsResponse)
def sync_code_default_prompts(
    auth_session: AuthSession = Depends(require_admin_session),
    service: AdminPromptService = Depends(get_admin_prompt_service),
) -> PromptSyncCodeDefaultsResponse:
    return PromptSyncCodeDefaultsResponse(**service.sync_code_default_versions(auth_session.username))


@router.get("/{prompt_key}", response_model=PromptDetailResponse)
def get_prompt_detail(
    prompt_key: str,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AdminPromptService = Depends(get_admin_prompt_service),
) -> PromptDetailResponse:
    try:
        return PromptDetailResponse(**service.get_prompt_detail(prompt_key))
    except PromptNotFoundError as exc:
        raise _handle_prompt_error(exc) from exc


@router.post("/{prompt_key}/versions/from-code-default", response_model=PromptMutationResponse)
def create_prompt_version_from_code_default(
    prompt_key: str,
    auth_session: AuthSession = Depends(require_admin_session),
    service: AdminPromptService = Depends(get_admin_prompt_service),
) -> PromptMutationResponse:
    try:
        prompt, message = service.create_version_from_code_default(prompt_key, created_by=auth_session.username)
        return PromptMutationResponse(prompt=prompt, message=message)
    except (PromptNotFoundError, PromptValidationError) as exc:
        raise _handle_prompt_error(exc) from exc


@router.post("/{prompt_key}/versions", response_model=PromptMutationResponse)
def create_prompt_version(
    prompt_key: str,
    payload: PromptCreateVersionRequest,
    auth_session: AuthSession = Depends(require_admin_session),
    service: AdminPromptService = Depends(get_admin_prompt_service),
) -> PromptMutationResponse:
    try:
        prompt = service.create_version(prompt_key, payload, created_by=auth_session.username)
        return PromptMutationResponse(prompt=prompt, message="Prompt version created")
    except (PromptNotFoundError, PromptValidationError) as exc:
        raise _handle_prompt_error(exc) from exc


@router.post("/{prompt_key}/versions/{version}/activate", response_model=PromptMutationResponse)
def activate_prompt_version(
    prompt_key: str,
    version: str,
    payload: PromptActivateRequest | None = None,
    auth_session: AuthSession = Depends(require_admin_session),
    service: AdminPromptService = Depends(get_admin_prompt_service),
) -> PromptMutationResponse:
    try:
        prompt = service.activate_version(
            prompt_key,
            version,
            activated_by=auth_session.username,
            change_note=payload.change_note if payload else None,
        )
        return PromptMutationResponse(prompt=prompt, message="Prompt version activated")
    except (PromptNotFoundError, PromptVersionNotFoundError) as exc:
        raise _handle_prompt_error(exc) from exc


@router.get("/{prompt_key}/runtime", response_model=PromptRuntimeResponse)
def get_runtime_prompt(
    prompt_key: str,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AdminPromptService = Depends(get_admin_prompt_service),
) -> PromptRuntimeResponse:
    try:
        return PromptRuntimeResponse(**service.get_runtime_prompt(prompt_key))
    except PromptNotFoundError as exc:
        raise _handle_prompt_error(exc) from exc
