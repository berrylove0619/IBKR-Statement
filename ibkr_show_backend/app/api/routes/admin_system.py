from fastapi import APIRouter, Depends

from app.api.deps import get_cache_client, get_es_client, require_admin_session
from app.core.auth import AuthSession
from app.core.config import Settings, get_settings
from app.schemas.admin_system_status import AdminSystemStatusResponse
from app.services.admin_system_status_service import AdminSystemStatusService

router = APIRouter(prefix="/admin/system", tags=["admin-system"])


@router.get("/status", response_model=AdminSystemStatusResponse)
def get_system_status(
    _admin: AuthSession = Depends(require_admin_session),
    settings: Settings = Depends(get_settings),
) -> AdminSystemStatusResponse:
    service = AdminSystemStatusService(settings, get_es_client(), get_cache_client())
    return service.build_status()
