"""
Longbridge MCP client wrapper - only read-only market data calls.

Environment config:
  LONGBRIDGE_MCP_ENABLED=false
  LONGBRIDGE_MCP_ENDPOINT=https://openapi.longbridge.com/mcp
  LONGBRIDGE_MCP_TIMEOUT_SECONDS=20
  LONGBRIDGE_MCP_MAX_RETRIES=1

Does NOT expose any trading/order/account/write tools.
"""

from __future__ import annotations

import logging
import os
import time
import json
from dataclasses import dataclass
from threading import Lock
from typing import Any

import httpx

from app.core.config import Settings
from app.services.longbridge_oauth_token_service import LongbridgeOAuthTokenService

logger = logging.getLogger(__name__)
MCP_PROTOCOL_VERSION = "2025-06-18"


@dataclass(frozen=True)
class LongbridgeMCPConfig:
    enabled: bool
    endpoint: str
    timeout_seconds: int
    max_retries: int


def _read_bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def get_longbridge_mcp_config(settings: Settings | None = None) -> LongbridgeMCPConfig:
    """Build MCP config from environment / settings."""
    enable = _read_bool_env("LONGBRIDGE_MCP_ENABLED", False)

    return LongbridgeMCPConfig(
        enabled=enable,
        endpoint=os.getenv("LONGBRIDGE_MCP_ENDPOINT", "https://openapi.longbridge.com/mcp"),
        timeout_seconds=int(os.getenv("LONGBRIDGE_MCP_TIMEOUT_SECONDS", "20")),
        max_retries=int(os.getenv("LONGBRIDGE_MCP_MAX_RETRIES", "1")),
    )


class LongbridgeMCPError(Exception):
    """Base MCP error."""
    def __init__(self, error_code: str, message: str, data_limitations: list[str] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.data_limitations = data_limitations or []


class MCPUnavailableError(LongbridgeMCPError):
    """MCP is disabled or unreachable."""
    def __init__(self, message: str = "Longbridge MCP is not available", data_limitations: list[str] | None = None) -> None:
        super().__init__("MCP_UNAVAILABLE", message, data_limitations)


class MCPtoolError(LongbridgeMCPError):
    """A specific MCP tool call failed."""
    def __init__(self, tool_name: str, message: str, data_limitations: list[str] | None = None) -> None:
        super().__init__(f"MCP_TOOL_ERROR:{tool_name}", message, data_limitations)


# Forbidden keywords - blocked even if not in explicit FORBIDDEN set
_FORBIDDEN_TOOL_NAMES = frozenset({
    "submit_order",
    "replace_order",
    "cancel_order",
    "dca_create",
    "dca_update",
    "dca_pause",
    "dca_resume",
    "dca_stop",
    "withdrawal",
    "withdrawals",
    "account_statement",
    "account_balance",
    "stock_positions",
    "orders",
    "today_orders",
    "history_orders",
    "order_detail",
    "executions",
    "today_executions",
    "history_executions",
    "trade_context",
    "positions",
    "deposits",
    "bank_cards",
    "ipo_orders",
    "ipo_order_detail",
})

_FORBIDDEN_NAME_PARTS = (
    "submit_order",
    "replace_order",
    "cancel_order",
    "withdraw",
    "deposit",
    "account_balance",
    "account_statement",
    "stock_positions",
    "order_detail",
    "today_orders",
    "history_orders",
    "today_executions",
    "history_executions",
)


def _is_forbidden_tool(tool_name: str) -> bool:
    """Check if tool name matches forbidden list or contains sensitive keywords."""
    name_lower = tool_name.lower()
    if name_lower in _FORBIDDEN_TOOL_NAMES:
        return True
    return any(part in name_lower for part in _FORBIDDEN_NAME_PARTS)


class LongbridgeMCPClient:
    """
    HTTP-based MCP client for Longbridge read-only market data.

    All tools return structured dicts, never raise to the caller.
    On error, returns {"ok": False, "error_code": "...", "message": "...", "data_limitations": [...]
    """

    def __init__(
        self,
        config: LongbridgeMCPConfig | None = None,
        settings: Settings | None = None,
        token_service: LongbridgeOAuthTokenService | None = None,
    ) -> None:
        self.config = config or get_longbridge_mcp_config(settings)
        self.token_service = token_service or LongbridgeOAuthTokenService(settings)
        self._client: httpx.Client | None = None
        self._initialized = False
        self._init_lock = Lock()
        if self.config.enabled:
            self._client = httpx.Client(
                base_url=self.config.endpoint,
                timeout=httpx.Timeout(self.config.timeout_seconds),
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                    "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
                },
            )

    @property
    def enabled(self) -> bool:
        return self.config.enabled and self._client is not None

    def health(self) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "error_code": "MCP_UNAVAILABLE", "message": "MCP disabled or not configured"}
        token_status = self.token_service.status()
        has_token = bool(token_status.get("mcp_effective_connected"))
        return {
            "ok": has_token,
            "enabled": True,
            "endpoint": self.config.endpoint,
            "auth_mode": "unified_openapi_oauth",
            "token_source": "openapi_oauth_store",
            "oauth_connected": bool(token_status.get("openapi_connected")),
            "auto_refresh_enabled": True,
            "refresh_available": bool(token_status.get("refresh_available")),
            "message": "MCP is using Longbridge OpenAPI OAuth token" if has_token else "LongBridge OpenAPI OAuth authorization is required",
        }

    def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Call an MCP tool by name with arguments.
        Returns structured result - never raises.
        """
        if not self.enabled:
            return {
                "ok": False,
                "error_code": "MCP_UNAVAILABLE",
                "message": "Longbridge MCP is not enabled or not configured",
                "data_limitations": ["MCP is disabled or access token not set"],
            }
        auth_header = self._authorization_header()
        if not auth_header:
            return {
                "ok": False,
                "error_code": "MCP_AUTH_REQUIRED",
                "message": "LongBridge OpenAPI OAuth authorization is required for MCP",
                "data_limitations": ["Complete LongBridge OpenAPI OAuth authorization in the admin console before using MCP"],
            }

        init_error = self._ensure_initialized()
        if init_error is not None:
            return init_error

        # Security: block forbidden tools by keyword
        if _is_forbidden_tool(tool_name):
            return {
                "ok": False,
                "error_code": "MCP_TOOL_FORBIDDEN",
                "message": f"Tool '{tool_name}' is forbidden for security reasons",
                "data_limitations": [f"Tool '{tool_name}' is not allowed: write/trade operations are forbidden"],
            }

        arguments = arguments or {}
        payload = {
            "jsonrpc": "2.0",
            "id": f"lb-{int(time.time() * 1000)}",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }

        for attempt in range(self.config.max_retries + 1):
            try:
                response = self._client.post(
                    "/",
                    json=payload,
                    headers={"Authorization": auth_header},
                    timeout=httpx.Timeout(self.config.timeout_seconds),
                )
                if response.status_code == 404:
                    return {
                        "ok": False,
                        "error_code": "MCP_TOOL_NOT_FOUND",
                        "message": f"Tool '{tool_name}' not found in Longbridge MCP",
                        "data_limitations": [f"Tool '{tool_name}' does not exist in MCP registry"],
                    }
                response.raise_for_status()
                result = self._decode_mcp_response(response)
                if isinstance(result, dict) and result.get("error"):
                    return {
                        "ok": False,
                        "error_code": f"MCP_TOOL_ERROR:{tool_name}",
                        "message": str(result["error"].get("message", "Unknown error")),
                        "data_limitations": [f"MCP tool '{tool_name}' returned error"],
                    }
                data = self._normalize_tool_result(result.get("result") if isinstance(result, dict) else result)
                return {"ok": True, "data": data}
            except httpx.TimeoutException:
                if attempt < self.config.max_retries:
                    continue
                return {
                    "ok": False,
                    "error_code": "MCP_TIMEOUT",
                    "message": f"MCP tool '{tool_name}' timed out after {self.config.timeout_seconds}s",
                    "data_limitations": [f"Tool '{tool_name}' timed out"],
                }
            except httpx.HTTPStatusError as exc:
                return {
                    "ok": False,
                    "error_code": f"MCP_HTTP_{exc.response.status_code}",
                    "message": f"MCP returned HTTP {exc.response.status_code}: {str(exc)[:200]}",
                    "data_limitations": [f"MCP HTTP error {exc.response.status_code}"],
                }
            except Exception as exc:
                if attempt < self.config.max_retries:
                    continue
                logger.warning("MCP tool %s failed after retries: %s", tool_name, exc)
                return {
                    "ok": False,
                    "error_code": f"MCP_ERROR:{tool_name}",
                    "message": str(exc)[:200],
                    "data_limitations": [f"MCP tool '{tool_name}' failed: {str(exc)[:100]}"],
                }

        return {
            "ok": False,
            "error_code": "MCP_MAX_RETRIES",
            "message": f"MCP tool '{tool_name}' failed after {self.config.max_retries + 1} attempts",
            "data_limitations": [f"Tool '{tool_name}' failed after retries"],
        }

    def list_tools(self) -> dict[str, Any]:
        if not self.enabled:
            return {
                "ok": False,
                "error_code": "MCP_UNAVAILABLE",
                "message": "Longbridge MCP is not enabled",
                "data_limitations": ["MCP is disabled"],
            }
        auth_header = self._authorization_header()
        if not auth_header:
            return {
                "ok": False,
                "error_code": "MCP_AUTH_REQUIRED",
                "message": "LongBridge OpenAPI OAuth authorization is required for MCP",
                "data_limitations": ["Complete LongBridge OpenAPI OAuth authorization in the admin console before using MCP"],
            }
        init_error = self._ensure_initialized()
        if init_error is not None:
            return init_error
        payload = {
            "jsonrpc": "2.0",
            "id": f"tools-{int(time.time() * 1000)}",
            "method": "tools/list",
            "params": {},
        }
        try:
            response = self._client.post(
                "/",
                json=payload,
                headers={"Authorization": auth_header},
                timeout=httpx.Timeout(self.config.timeout_seconds),
            )
            response.raise_for_status()
            result = self._decode_mcp_response(response)
            if isinstance(result, dict) and result.get("error"):
                return {
                    "ok": False,
                    "error_code": "MCP_LIST_TOOLS_ERROR",
                    "message": str(result["error"].get("message", "MCP tools/list failed")),
                    "data_limitations": ["MCP tools/list returned an error"],
                }
            return {"ok": True, "data": result.get("result") if isinstance(result, dict) else result}
        except Exception as exc:
            return {
                "ok": False,
                "error_code": "MCP_LIST_TOOLS_FAILED",
                "message": str(exc)[:200],
                "data_limitations": [f"MCP tools/list failed: {str(exc)[:100]}"],
            }

    def _ensure_initialized(self) -> dict[str, Any] | None:
        if self._initialized:
            return None
        with self._init_lock:
            if self._initialized:
                return None
            auth_header = self._authorization_header()
            if not auth_header:
                return {
                    "ok": False,
                    "error_code": "MCP_AUTH_REQUIRED",
                    "message": "LongBridge OpenAPI OAuth authorization is required for MCP",
                    "data_limitations": ["Complete LongBridge OpenAPI OAuth authorization in the admin console before using MCP"],
                }
            payload = {
                "jsonrpc": "2.0",
                "id": f"init-{int(time.time() * 1000)}",
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "ibkr_show_backend", "version": "1"},
                },
            }
            try:
                response = self._client.post(
                    "/",
                    json=payload,
                    headers={"Authorization": auth_header},
                    timeout=httpx.Timeout(self.config.timeout_seconds),
                )
                response.raise_for_status()
                result = self._decode_mcp_response(response)
                if isinstance(result, dict) and result.get("error"):
                    return {
                        "ok": False,
                        "error_code": "MCP_INITIALIZE_FAILED",
                        "message": str(result["error"].get("message", "MCP initialize failed"))[:200],
                        "data_limitations": ["MCP initialize returned an error"],
                    }
                self._initialized = True
                return None
            except httpx.HTTPStatusError as exc:
                return {
                    "ok": False,
                    "error_code": f"MCP_HTTP_{exc.response.status_code}",
                    "message": f"MCP initialize returned HTTP {exc.response.status_code}: {str(exc)[:200]}",
                    "data_limitations": [f"MCP initialize HTTP error {exc.response.status_code}"],
                }
            except Exception as exc:
                return {
                    "ok": False,
                    "error_code": "MCP_INITIALIZE_FAILED",
                    "message": str(exc)[:200],
                    "data_limitations": [f"MCP initialize failed: {str(exc)[:100]}"],
                }

    def _authorization_header(self) -> str | None:
        access_token = self.token_service.get_mcp_access_token()
        if not access_token:
            return None
        return f"Bearer {access_token}"

    def _decode_mcp_response(self, response: httpx.Response) -> Any:
        text = response.text.strip()
        if text.startswith("data:"):
            for line in text.splitlines():
                if line.startswith("data:"):
                    payload = line[5:].strip()
                    if payload:
                        return json.loads(payload)
        return response.json()

    def _normalize_tool_result(self, result: Any) -> Any:
        if not isinstance(result, dict) or "content" not in result:
            return result
        content = result.get("content")
        if not isinstance(content, list) or not content:
            return result
        first = content[0]
        if not isinstance(first, dict):
            return result
        text = first.get("text")
        if not isinstance(text, str):
            return result
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"text": text}
