from __future__ import annotations

from typing import Any

from app.core.config import Settings, get_settings
from app.services.longbridge_openapi_oauth import LongbridgeOpenAPIOAuthService
from app.services.oauth_utils import mask_token


class LongbridgeOAuthTokenService:
    """Unified LongBridge auth facade backed only by OpenAPI OAuth."""

    def __init__(
        self,
        settings: Settings | None = None,
        openapi_oauth_service: LongbridgeOpenAPIOAuthService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.openapi_oauth_service = openapi_oauth_service or LongbridgeOpenAPIOAuthService(self.settings)

    def get_access_token(self) -> str | None:
        return self.openapi_oauth_service.get_access_token()

    def get_mcp_access_token(self) -> str | None:
        return self.get_access_token()

    def get_openapi_access_token(self) -> str | None:
        return self.get_access_token()

    def refresh(self) -> dict[str, Any]:
        self.openapi_oauth_service.refresh_token()
        return self.status()

    def status(self) -> dict[str, Any]:
        status = self.openapi_oauth_service.status()
        client_id = str(status.get("client_id") or "")
        openapi_connected = bool(status.get("oauth_connected"))
        return {
            "auth_mode": "unified_openapi_oauth",
            "token_source": "openapi_oauth_store",
            "unified_oauth_enabled": True,
            "openapi_connected": openapi_connected,
            "mcp_effective_connected": openapi_connected,
            "client_id_masked": mask_token(client_id),
            "has_access_token": bool(status.get("has_access_token")),
            "has_refresh_token": bool(status.get("has_refresh_token")),
            "refresh_available": bool(status.get("refresh_available")),
            "expires_at": status.get("expires_at"),
            "expires_in_seconds": status.get("expires_in_seconds"),
            "auto_registered": bool(status.get("auto_registered")),
            "registration_client_uri": str(status.get("registration_client_uri") or ""),
            "message": "LongBridge OpenAPI OAuth token is shared by OpenAPI / SDK and MCP"
            if openapi_connected
            else "LongBridge OpenAPI OAuth authorization is required",
        }

    def health(self) -> dict[str, Any]:
        return self.status()
