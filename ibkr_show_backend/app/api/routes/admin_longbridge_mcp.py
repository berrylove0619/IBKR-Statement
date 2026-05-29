from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse

from app.api.deps import get_longbridge_oauth_token_service, require_admin_session
from app.core.auth import AuthSession
from app.schemas.admin_longbridge_mcp import (
    LongbridgeMCPTestResponse,
    LongbridgeUnifiedOAuthMutationResponse,
    LongbridgeUnifiedOAuthStatusResponse,
)
from app.services.longbridge_oauth_token_service import LongbridgeOAuthTokenService
from app.services.mcp.longbridge_mcp_client import LongbridgeMCPClient, get_longbridge_mcp_config

router = APIRouter(tags=["admin-longbridge"])


def _mcp_client(service: LongbridgeOAuthTokenService) -> LongbridgeMCPClient:
    return LongbridgeMCPClient(
        config=get_longbridge_mcp_config(service.settings),
        settings=service.settings,
        token_service=service,
    )


def _unified_status(service: LongbridgeOAuthTokenService) -> LongbridgeUnifiedOAuthStatusResponse:
    mcp_config = get_longbridge_mcp_config(service.settings)
    status_payload = service.status()
    return LongbridgeUnifiedOAuthStatusResponse(
        **status_payload,
        mcp_endpoint=mcp_config.endpoint,
        openapi_sdk_connected=bool(status_payload.get("openapi_connected")),
    )


@router.get("/admin/longbridge/oauth/status", response_model=LongbridgeUnifiedOAuthStatusResponse)
def get_longbridge_unified_oauth_status(
    _auth_session: AuthSession = Depends(require_admin_session),
    service: LongbridgeOAuthTokenService = Depends(get_longbridge_oauth_token_service),
) -> LongbridgeUnifiedOAuthStatusResponse:
    return _unified_status(service)


@router.get("/admin/longbridge/oauth/health", response_model=LongbridgeUnifiedOAuthStatusResponse)
def get_longbridge_unified_oauth_health(
    _auth_session: AuthSession = Depends(require_admin_session),
    service: LongbridgeOAuthTokenService = Depends(get_longbridge_oauth_token_service),
) -> LongbridgeUnifiedOAuthStatusResponse:
    return _unified_status(service)


@router.post("/admin/longbridge/oauth/refresh", response_model=LongbridgeUnifiedOAuthMutationResponse)
def refresh_longbridge_unified_oauth(
    _auth_session: AuthSession = Depends(require_admin_session),
    service: LongbridgeOAuthTokenService = Depends(get_longbridge_oauth_token_service),
) -> LongbridgeUnifiedOAuthMutationResponse:
    service.refresh()
    return LongbridgeUnifiedOAuthMutationResponse(
        success=True,
        message="LongBridge OAuth token refreshed",
        status=_unified_status(service),
    )


@router.get("/admin/longbridge-mcp/status", response_model=LongbridgeUnifiedOAuthStatusResponse)
def get_longbridge_mcp_status(
    _auth_session: AuthSession = Depends(require_admin_session),
    service: LongbridgeOAuthTokenService = Depends(get_longbridge_oauth_token_service),
) -> LongbridgeUnifiedOAuthStatusResponse:
    return _unified_status(service)


@router.api_route("/admin/longbridge-mcp/oauth/{removed_path:path}", methods=["GET", "POST"])
@router.api_route("/admin/longbridge-mcp/refresh", methods=["POST"])
@router.api_route("/admin/longbridge-mcp/disconnect", methods=["POST"])
def removed_legacy_mcp_oauth_endpoint(
    removed_path: str = "",
    _auth_session: AuthSession = Depends(require_admin_session),
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_410_GONE,
        content={
            "detail": "Standalone LongBridge MCP authorization endpoints have been removed. Use LongBridge OpenAPI OAuth as the unified authorization source.",
        },
    )


@router.post("/admin/longbridge-mcp/test-tool")
def test_individual_mcp_tool(
    tool_name: str = Query(..., description="MCP tool name to test"),
    symbol: str = Query(default="AAPL.US", description="Symbol to test with"),
    _auth_session: AuthSession = Depends(require_admin_session),
    service: LongbridgeOAuthTokenService = Depends(get_longbridge_oauth_token_service),
) -> dict:
    """Diagnostic endpoint: test a specific MCP tool via the adapter."""
    from app.services.mcp.longbridge_mcp_tools import LongbridgeMCPToolAdapter, _map_tool_call

    client = _mcp_client(service)
    adapter = LongbridgeMCPToolAdapter(client)

    args = {"symbol": symbol}
    if tool_name == "financial_report":
        args = {"symbol": symbol, "kind": "ALL", "period": "qf", "count": 4}
    elif tool_name == "candlesticks":
        args = {"symbol": symbol, "period": "day", "count": 30}
    elif tool_name == "news_search":
        args = {"symbol": symbol, "limit": 5}

    mcp_tool_name, mcp_args = _map_tool_call(tool_name, args)
    raw_result = client.call_tool(mcp_tool_name, mcp_args)
    result = adapter.call(tool_name, args)
    return {
        "tool_name": tool_name,
        "mcp_tool_name": mcp_tool_name,
        "arguments": args,
        "ok": result.get("ok"),
        "data": result.get("data"),
        "raw_ok": raw_result.get("ok"),
        "raw_data": raw_result.get("data"),
        "raw_error": raw_result.get("error_code"),
        "raw_message": raw_result.get("message"),
        "error_code": result.get("error_code"),
        "message": result.get("message"),
    }


@router.post("/admin/longbridge-mcp/test", response_model=LongbridgeMCPTestResponse)
def test_longbridge_mcp_connection(
    _auth_session: AuthSession = Depends(require_admin_session),
    service: LongbridgeOAuthTokenService = Depends(get_longbridge_oauth_token_service),
) -> LongbridgeMCPTestResponse:
    client = _mcp_client(service)
    tools_result = client.list_tools()
    if not tools_result.get("ok"):
        return LongbridgeMCPTestResponse(
            success=False,
            message=str(tools_result.get("message") or "MCP tools/list failed"),
            error_code=str(tools_result.get("error_code") or ""),
            data_limitations=[str(item) for item in tools_result.get("data_limitations", [])],
        )

    tools_data = tools_result.get("data") if isinstance(tools_result.get("data"), dict) else {}
    tools = tools_data.get("tools", []) if isinstance(tools_data, dict) else []
    quote_result = client.call_tool("quote", {"symbols": ["AAPL.US"]})
    if not quote_result.get("ok"):
        return LongbridgeMCPTestResponse(
            success=False,
            message=str(quote_result.get("message") or "MCP quote test failed"),
            tool_count=len(tools) if isinstance(tools, list) else None,
            error_code=str(quote_result.get("error_code") or ""),
            data_limitations=[str(item) for item in quote_result.get("data_limitations", [])],
        )

    return LongbridgeMCPTestResponse(
        success=True,
        message="Longbridge MCP is connected through unified OpenAPI OAuth",
        tool_count=len(tools) if isinstance(tools, list) else None,
        quote_sample=quote_result.get("data") if isinstance(quote_result.get("data"), dict) else {"value": quote_result.get("data")},
    )
