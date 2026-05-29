from pathlib import Path

from fastapi.testclient import TestClient

from app.api.deps import get_admin_ibkr_service
from app.core.config import get_settings
from app.main import app
from app.schemas.admin_ibkr import (
    IBKRFlexSettingsResponse,
    IBKRFlexTestResponse,
    IBKRImportResponse,
)
from app.services.admin_ibkr_service import IBKRFlexConfig, IBKRFlexConfigStore, mask_flex_token


class DummyAdminIBKRService:
    def __init__(self) -> None:
        self.imported_filename = ""
        self.imported_content = b""

    def get_settings(self) -> IBKRFlexSettingsResponse:
        return IBKRFlexSettingsResponse(
            query_id="123",
            flex_token_masked="****7890",
            has_flex_token=True,
            config_file="/tmp/ibkr_flex.json",
        )

    def update_settings(self, payload) -> IBKRFlexSettingsResponse:
        return IBKRFlexSettingsResponse(
            query_id=payload.query_id or "123",
            flex_token_masked=mask_flex_token(payload.flex_token or "token-7890"),
            has_flex_token=True,
            config_file="/tmp/ibkr_flex.json",
        )

    def test_connection(self) -> IBKRFlexTestResponse:
        return IBKRFlexTestResponse(success=True, query_id="123", reference_code="ABC", message="ok")

    def pull_daily_from_ibkr(self) -> IBKRImportResponse:
        return IBKRImportResponse(
            success=True,
            filename="daily.csv",
            result={"idx": {"index": "idx", "upserted": 1}},
            message="done",
        )

    def import_history_csv(self, filename: str, content: bytes) -> IBKRImportResponse:
        self.imported_filename = filename
        self.imported_content = content
        return IBKRImportResponse(
            success=True,
            filename=filename,
            result={"idx": {"index": "idx", "upserted": 2}},
            message="imported",
        )


def _login(client: TestClient) -> None:
    settings = get_settings()
    response = client.post(
        "/api/auth/login",
        json={"username": settings.auth_username, "password": settings.auth_password},
    )
    assert response.status_code == 200


def test_admin_ibkr_config_store_round_trips_secret(tmp_path: Path) -> None:
    config_file = tmp_path / "ibkr_flex.json"
    store = IBKRFlexConfigStore(str(config_file))

    store.save(IBKRFlexConfig(query_id="query-1", flex_token="token-123456"))
    config = store.read()

    assert config.query_id == "query-1"
    assert config.flex_token == "token-123456"
    assert mask_flex_token(config.flex_token) == "****3456"


def test_admin_ibkr_routes_require_login() -> None:
    client = TestClient(app)

    response = client.get("/api/admin/ibkr/settings")

    assert response.status_code == 401


def test_admin_ibkr_settings_and_import_routes_call_service() -> None:
    client = TestClient(app)
    service = DummyAdminIBKRService()
    app.dependency_overrides[get_admin_ibkr_service] = lambda: service

    try:
        _login(client)
        settings_response = client.get("/api/admin/ibkr/settings")
        update_response = client.put(
            "/api/admin/ibkr/settings",
            json={"query_id": "456", "flex_token": "token-9999"},
        )
        import_response = client.post(
            "/api/admin/ibkr/import-history",
            content=b"header\nvalue\n",
            headers={"x-filename": "history.csv", "content-type": "text/csv"},
        )
    finally:
        app.dependency_overrides.clear()

    assert settings_response.status_code == 200
    assert settings_response.json()["query_id"] == "123"
    assert update_response.status_code == 200
    assert update_response.json()["settings"]["query_id"] == "456"
    assert import_response.status_code == 200
    assert import_response.json()["result"]["idx"]["upserted"] == 2
    assert service.imported_filename == "history.csv"
    assert service.imported_content == b"header\nvalue\n"
