import json
import os

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.services.admin_bootstrap_service import AdminAuthStore, AdminAuthService

client = TestClient(app)


def _make_service(tmp_path) -> AdminAuthService:
    settings = get_settings()
    config_file = str(tmp_path / "admin_auth.json")
    # Patch the settings to use our temp config file
    object.__setattr__(settings, "admin_auth_config_file", config_file)
    return AdminAuthService(settings, AdminAuthStore(config_file))


def test_bootstrap_status_returns_not_initialized_when_no_file(tmp_path) -> None:
    service = _make_service(tmp_path)
    status = service.status()
    assert status["initialized"] is False
    assert status["auth_source"] == "env"


def test_bootstrap_init_creates_admin(tmp_path) -> None:
    service = _make_service(tmp_path)
    result = service.bootstrap("testadmin", "password123")
    assert result.initialized is True
    assert result.username == "testadmin"

    status = service.status()
    assert status["initialized"] is True
    assert status["auth_source"] == "file"


def test_bootstrap_init_rejects_duplicate(tmp_path) -> None:
    service = _make_service(tmp_path)
    service.bootstrap("testadmin", "password123")

    try:
        service.bootstrap("another", "password456")
        assert False, "Should have raised ValueError"
    except ValueError as exc:
        assert "已初始化" in str(exc)


def test_bootstrap_init_rejects_empty_username(tmp_path) -> None:
    service = _make_service(tmp_path)
    try:
        service.bootstrap("", "password123")
        assert False, "Should have raised ValueError"
    except ValueError as exc:
        assert "用户名" in str(exc)


def test_bootstrap_init_rejects_short_password(tmp_path) -> None:
    service = _make_service(tmp_path)
    try:
        service.bootstrap("admin", "short")
        assert False, "Should have raised ValueError"
    except ValueError as exc:
        assert "8" in str(exc)


def test_bootstrap_then_login_with_correct_password(tmp_path) -> None:
    service = _make_service(tmp_path)
    service.bootstrap("myadmin", "securepass123")
    assert service.verify_password("myadmin", "securepass123") is True


def test_bootstrap_then_login_with_wrong_password(tmp_path) -> None:
    service = _make_service(tmp_path)
    service.bootstrap("myadmin", "securepass123")
    assert service.verify_password("myadmin", "wrongpassword") is False
    assert service.verify_password("wronguser", "securepass123") is False


def test_env_fallback_login_when_not_initialized(tmp_path) -> None:
    service = _make_service(tmp_path)
    settings = get_settings()
    assert service.verify_password(settings.auth_username, settings.auth_password) is True
    assert service.verify_password(settings.auth_username, "wrong") is False


def test_session_secret_changes_after_bootstrap(tmp_path) -> None:
    service = _make_service(tmp_path)
    env_secret = service.get_session_secret()
    service.bootstrap("admin", "password123")
    file_secret = service.get_session_secret()
    assert file_secret != env_secret


def test_bootstrap_file_has_0600_permissions(tmp_path) -> None:
    service = _make_service(tmp_path)
    service.bootstrap("admin", "password123")
    mode = os.stat(service.store.config_file).st_mode & 0o777
    assert mode == 0o600


def test_password_hash_is_not_plaintext(tmp_path) -> None:
    service = _make_service(tmp_path)
    service.bootstrap("admin", "password123")
    data = service.store.read()
    assert data.password_hash != "password123"
    assert data.salt != ""
    assert len(data.password_hash) == 64  # sha256 hex digest


def test_bootstrap_api_status_endpoint(tmp_path) -> None:
    response = client.get("/api/auth/bootstrap/status")
    assert response.status_code == 200
    payload = response.json()
    assert "initialized" in payload
    assert "auth_source" in payload


def _patch_admin_auth_config(monkeypatch, tmp_path) -> str:
    config_file = str(tmp_path / "admin_auth.json")
    monkeypatch.setenv("ADMIN_AUTH_CONFIG_FILE", config_file)
    get_settings.cache_clear()
    return config_file


def test_bootstrap_api_init_endpoint(tmp_path, monkeypatch) -> None:
    _patch_admin_auth_config(monkeypatch, tmp_path)

    response = client.post(
        "/api/auth/bootstrap/init",
        json={"username": "apiadmin", "password": "apipassword123"},
    )
    assert response.status_code == 200
    assert response.json()["initialized"] is True


def test_bootstrap_api_rejects_duplicate_init(tmp_path, monkeypatch) -> None:
    _patch_admin_auth_config(monkeypatch, tmp_path)

    client.post("/api/auth/bootstrap/init", json={"username": "admin", "password": "password123"})
    response = client.post(
        "/api/auth/bootstrap/init",
        json={"username": "admin2", "password": "password456"},
    )
    assert response.status_code == 409


def test_bootstrap_api_rejects_weak_password(tmp_path, monkeypatch) -> None:
    _patch_admin_auth_config(monkeypatch, tmp_path)

    response = client.post(
        "/api/auth/bootstrap/init",
        json={"username": "admin", "password": "short"},
    )
    assert response.status_code == 400


def test_full_flow_bootstrap_then_login_via_api(tmp_path, monkeypatch) -> None:
    _patch_admin_auth_config(monkeypatch, tmp_path)

    # Bootstrap
    init_response = client.post(
        "/api/auth/bootstrap/init",
        json={"username": "newadmin", "password": "newpassword123"},
    )
    assert init_response.status_code == 200

    # Login with new credentials
    login_response = client.post(
        "/api/auth/login",
        json={"username": "newadmin", "password": "newpassword123"},
    )
    assert login_response.status_code == 200
    assert login_response.json()["authenticated"] is True
    assert login_response.json()["username"] == "newadmin"

    # Session should be authenticated
    session_response = client.get("/api/auth/session")
    assert session_response.status_code == 200
    assert session_response.json()["authenticated"] is True

    # Wrong password should fail
    bad_login = client.post(
        "/api/auth/login",
        json={"username": "newadmin", "password": "wrongpassword"},
    )
    assert bad_login.status_code == 401


def test_corrupted_bootstrap_file_falls_back_to_env(tmp_path) -> None:
    config_file = tmp_path / "admin_auth.json"
    config_file.write_text("not valid json{{{", encoding="utf-8")
    service = AdminAuthService(get_settings(), AdminAuthStore(config_file))
    assert service.is_initialized() is False
    settings = get_settings()
    assert service.verify_password(settings.auth_username, settings.auth_password) is True
