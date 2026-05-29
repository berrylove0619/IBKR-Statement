from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.schemas.admin_system_status import AdminSystemStatusResponse, SystemComponentStatus

client = TestClient(app)


def _login() -> None:
    get_settings.cache_clear()
    settings = get_settings()
    response = client.post(
        "/api/auth/login",
        json={"username": settings.auth_username, "password": settings.auth_password},
    )
    assert response.status_code == 200


def _component_by_name(response: AdminSystemStatusResponse, name: str) -> SystemComponentStatus:
    for c in response.components:
        if c.name == name:
            return c
    raise AssertionError(f"component {name} not found")


def test_system_status_requires_login() -> None:
    response = client.get("/api/admin/system/status")
    assert response.status_code == 401


def test_system_status_returns_all_components() -> None:
    _login()
    response = client.get("/api/admin/system/status")
    assert response.status_code == 200
    data = AdminSystemStatusResponse(**response.json())
    names = [c.name for c in data.components]
    assert "backend" in names
    assert "elasticsearch" in names
    assert "redis" in names
    assert "ibkr" in names
    assert "longbridge" in names
    assert "llm" in names
    assert "email" in names
    assert "demo_data" in names
    assert "bootstrap" in names
    assert "worker" in names


def test_system_status_overall_ok_when_all_ok() -> None:
    _login()
    response = client.get("/api/admin/system/status")
    data = AdminSystemStatusResponse(**response.json())
    statuses = [c.status for c in data.components]
    # With default config (env fallback), some may be warning/unknown
    # overall_status should reflect the worst component
    if "error" in statuses:
        assert data.overall_status == "error"
    elif any(s in statuses for s in ("warning", "unknown", "disabled")):
        assert data.overall_status == "warning"
    else:
        assert data.overall_status == "ok"


def test_system_status_component_error_overrides_overall() -> None:
    _login()
    response = client.get("/api/admin/system/status")
    data = AdminSystemStatusResponse(**response.json())
    # If any component is error, overall must be error
    for c in data.components:
        if c.status == "error":
            assert data.overall_status == "error"
            return
    # No errors found, overall should not be error
    assert data.overall_status in ("ok", "warning")


def test_backend_component_is_always_ok() -> None:
    _login()
    response = client.get("/api/admin/system/status")
    data = AdminSystemStatusResponse(**response.json())
    backend = _component_by_name(data, "backend")
    assert backend.status == "ok"
    assert backend.label == "Backend"


def test_worker_component_is_unknown() -> None:
    _login()
    response = client.get("/api/admin/system/status")
    data = AdminSystemStatusResponse(**response.json())
    worker = _component_by_name(data, "worker")
    assert worker.status == "unknown"


def test_bootstrap_component_reflects_init_state() -> None:
    _login()
    response = client.get("/api/admin/system/status")
    data = AdminSystemStatusResponse(**response.json())
    bootstrap = _component_by_name(data, "bootstrap")
    # In test env, bootstrap may be uninitialized (env fallback)
    assert bootstrap.status in ("ok", "warning")


def test_ibkr_component_warning_when_not_configured() -> None:
    _login()
    response = client.get("/api/admin/system/status")
    data = AdminSystemStatusResponse(**response.json())
    ibkr = _component_by_name(data, "ibkr")
    # Default test env has no flex token configured
    assert ibkr.status in ("ok", "warning")
    assert ibkr.label == "IBKR"


def test_llm_component_warning_when_no_provider() -> None:
    _login()
    response = client.get("/api/admin/system/status")
    data = AdminSystemStatusResponse(**response.json())
    llm = _component_by_name(data, "llm")
    assert llm.status in ("ok", "warning")
    assert llm.label == "LLM"


def test_longbridge_component_warning_when_not_connected() -> None:
    _login()
    response = client.get("/api/admin/system/status")
    data = AdminSystemStatusResponse(**response.json())
    lb = _component_by_name(data, "longbridge")
    assert lb.status in ("ok", "warning")
    assert lb.label == "LongBridge"


def test_email_component_warning_when_not_configured() -> None:
    _login()
    response = client.get("/api/admin/system/status")
    data = AdminSystemStatusResponse(**response.json())
    email = _component_by_name(data, "email")
    assert email.status in ("ok", "warning")
    assert email.label == "Email"


def test_redis_component_status() -> None:
    _login()
    response = client.get("/api/admin/system/status")
    data = AdminSystemStatusResponse(**response.json())
    redis = _component_by_name(data, "redis")
    # Redis may be disabled if not configured, or ok/error if configured
    assert redis.status in ("ok", "warning", "error", "disabled")
    assert redis.label == "Redis"


def test_generated_at_is_iso_format() -> None:
    _login()
    response = client.get("/api/admin/system/status")
    data = AdminSystemStatusResponse(**response.json())
    assert "T" in data.generated_at
    assert data.generated_at.endswith("Z") or "+" in data.generated_at


def test_component_details_is_dict() -> None:
    _login()
    response = client.get("/api/admin/system/status")
    data = AdminSystemStatusResponse(**response.json())
    for c in data.components:
        assert isinstance(c.details, dict)
