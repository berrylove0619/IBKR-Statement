from fastapi.testclient import TestClient

from app.api.deps import get_longbridge_oauth_token_service
from app.core.config import get_settings
from app.main import app
from app.services.longbridge_oauth_token_service import LongbridgeOAuthTokenService


class FakeOpenAPIOAuthService:
    def __init__(self, token: str | None = "openapi-access-token") -> None:
        self.token = token
        self.refresh_called = False

    def get_access_token(self) -> str | None:
        return self.token

    def refresh_token(self):
        self.refresh_called = True
        return {"access_token": self.token}

    def status(self):
        return {
            "oauth_connected": bool(self.token),
            "client_id": "openapi-client-id",
            "has_access_token": bool(self.token),
            "has_refresh_token": True,
            "refresh_available": True,
            "expires_at": 4_102_444_800,
            "expires_in_seconds": 3600,
        }


class DummyUnifiedTokenRouteService:
    settings = get_settings()

    def __init__(self) -> None:
        self.refreshed = False

    def status(self):
        return {
            "auth_mode": "unified_openapi_oauth",
            "token_source": "openapi_oauth_store",
            "unified_oauth_enabled": True,
            "openapi_connected": True,
            "mcp_effective_connected": True,
            "client_id_masked": "****t-id",
            "has_access_token": True,
            "has_refresh_token": True,
            "refresh_available": True,
            "expires_at": 4_102_444_800,
            "expires_in_seconds": 3600,
            "message": "ok",
        }

    def refresh(self):
        self.refreshed = True
        return self.status()


def test_unified_token_service_uses_openapi_oauth_token() -> None:
    service = LongbridgeOAuthTokenService(openapi_oauth_service=FakeOpenAPIOAuthService("openapi-access-token"))

    assert service.get_access_token() == "openapi-access-token"
    assert service.get_mcp_access_token() == "openapi-access-token"
    assert service.get_openapi_access_token() == "openapi-access-token"
    status = service.status()
    assert status["auth_mode"] == "unified_openapi_oauth"
    assert status["token_source"] == "openapi_oauth_store"
    assert status["mcp_effective_connected"] is True
    assert "openapi-access-token" not in str(status)


def test_unified_token_service_refresh_delegates_to_openapi_oauth() -> None:
    openapi_service = FakeOpenAPIOAuthService("openapi-access-token")
    service = LongbridgeOAuthTokenService(openapi_oauth_service=openapi_service)

    service.refresh()

    assert openapi_service.refresh_called is True


def test_unified_oauth_admin_routes_require_login() -> None:
    client = TestClient(app)

    response = client.get("/api/admin/longbridge/oauth/status")

    assert response.status_code == 401


def test_unified_oauth_admin_routes_return_openapi_store_status() -> None:
    client = TestClient(app)
    app.dependency_overrides[get_longbridge_oauth_token_service] = lambda: DummyUnifiedTokenRouteService()
    try:
        _login(client)
        status_response = client.get("/api/admin/longbridge/oauth/status")
        health_response = client.get("/api/admin/longbridge/oauth/health")
        refresh_response = client.post("/api/admin/longbridge/oauth/refresh")
        removed_response = client.post("/api/admin/longbridge-mcp/oauth/start")
    finally:
        app.dependency_overrides.clear()

    assert status_response.status_code == 200
    assert status_response.json()["token_source"] == "openapi_oauth_store"
    assert status_response.json()["auth_mode"] == "unified_openapi_oauth"
    assert health_response.status_code == 200
    assert refresh_response.status_code == 200
    assert removed_response.status_code == 410


def _login(client: TestClient) -> None:
    settings = get_settings()
    response = client.post("/api/auth/login", json={"username": settings.auth_username, "password": settings.auth_password})
    assert response.status_code == 200
