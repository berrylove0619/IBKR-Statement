from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

REMOVED_MCP_TOKEN_ENV = "LONGBRIDGE_MCP_" + "ACCESS_TOKEN"


class FakeTokenService:
    def __init__(self, token: str | None = None, connected: bool = False, refresh_available: bool = False) -> None:
        self.token = token
        self.connected = connected
        self.refresh_available = refresh_available
        self.get_mcp_access_token_calls = 0

    def get_mcp_access_token(self) -> str | None:
        self.get_mcp_access_token_calls += 1
        return self.token

    def status(self) -> dict:
        return {
            "openapi_connected": self.connected,
            "mcp_effective_connected": self.connected,
            "refresh_available": self.refresh_available,
        }


def _settings(tmp_path):
    return SimpleNamespace()


def test_config_ignores_removed_mcp_token_env(monkeypatch):
    from app.services.mcp.longbridge_mcp_client import get_longbridge_mcp_config

    monkeypatch.setenv("LONGBRIDGE_MCP_ENABLED", "true")
    monkeypatch.setenv(REMOVED_MCP_TOKEN_ENV, "must-not-be-used")

    config = get_longbridge_mcp_config()

    assert config.enabled is True
    assert not hasattr(config, "access_token")


def test_authorization_header_uses_oauth_service_only(tmp_path, monkeypatch):
    from app.services.mcp.longbridge_mcp_client import LongbridgeMCPClient, LongbridgeMCPConfig

    monkeypatch.setenv(REMOVED_MCP_TOKEN_ENV, "must-not-be-used")
    token_service = FakeTokenService(token="oauth-token")
    client = LongbridgeMCPClient(
        config=LongbridgeMCPConfig(
            enabled=False,
            endpoint="https://openapi.longbridge.com/mcp",
            timeout_seconds=10,
            max_retries=0,
        ),
        settings=_settings(tmp_path),
        token_service=token_service,
    )

    assert client._authorization_header() == "Bearer oauth-token"
    assert token_service.get_mcp_access_token_calls == 1


def test_authorization_header_returns_none_without_oauth_token(tmp_path, monkeypatch):
    from app.services.mcp.longbridge_mcp_client import LongbridgeMCPClient, LongbridgeMCPConfig

    monkeypatch.setenv(REMOVED_MCP_TOKEN_ENV, "must-not-be-used")
    client = LongbridgeMCPClient(
        config=LongbridgeMCPConfig(
            enabled=False,
            endpoint="https://openapi.longbridge.com/mcp",
            timeout_seconds=10,
            max_retries=0,
        ),
        settings=_settings(tmp_path),
        token_service=FakeTokenService(token=None),
    )

    assert client._authorization_header() is None


def test_health_reports_unified_openapi_oauth_mode(tmp_path, monkeypatch):
    from app.services.mcp.longbridge_mcp_client import LongbridgeMCPClient, LongbridgeMCPConfig

    monkeypatch.setenv(REMOVED_MCP_TOKEN_ENV, "must-not-be-used")
    client = LongbridgeMCPClient(
        config=LongbridgeMCPConfig(
            enabled=True,
            endpoint="https://openapi.longbridge.com/mcp",
            timeout_seconds=10,
            max_retries=0,
        ),
        settings=_settings(tmp_path),
        token_service=FakeTokenService(token="oauth-token", connected=True, refresh_available=True),
    )

    health = client.health()

    assert health["ok"] is True
    assert health["auth_mode"] == "unified_openapi_oauth"
    assert health["token_source"] == "openapi_oauth_store"
    assert health["auto_refresh_enabled"] is True
    assert health["refresh_available"] is True


def test_call_tool_requires_unified_openapi_oauth_token(tmp_path, monkeypatch):
    from app.services.mcp.longbridge_mcp_client import LongbridgeMCPClient, LongbridgeMCPConfig

    monkeypatch.setenv(REMOVED_MCP_TOKEN_ENV, "must-not-be-used")
    client = LongbridgeMCPClient(
        config=LongbridgeMCPConfig(
            enabled=True,
            endpoint="https://openapi.longbridge.com/mcp",
            timeout_seconds=10,
            max_retries=0,
        ),
        settings=_settings(tmp_path),
        token_service=FakeTokenService(token=None, connected=False),
    )

    result = client.call_tool("quote", {"symbols": ["AAPL.US"]})

    assert result["ok"] is False
    assert result["error_code"] == "MCP_AUTH_REQUIRED"


def test_public_docs_do_not_mention_removed_mcp_token_env():
    removed_name = "LONGBRIDGE_MCP_" + "ACCESS_TOKEN"
    repo_root = Path(__file__).resolve().parents[2]
    candidate_paths = [
        *repo_root.glob("README*"),
        *repo_root.glob("docs/**/*.md"),
        *repo_root.glob("**/.env.example"),
    ]

    for path in candidate_paths:
        if path.is_file():
            assert removed_name not in path.read_text(encoding="utf-8")
