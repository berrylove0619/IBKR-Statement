from __future__ import annotations

from html import escape
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse

from app.api.deps import get_longbridge_external_data_client, get_longbridge_openapi_oauth_service, require_admin_session
from app.core.auth import AuthSession
from app.schemas.admin_longbridge_openapi import (
    LongbridgeOpenAPIHealthResponse,
    LongbridgeOpenAPIOAuthCompleteRequest,
    LongbridgeOpenAPIOAuthMutationResponse,
    LongbridgeOpenAPIOAuthStartRequest,
    LongbridgeOpenAPIOAuthStartResponse,
    LongbridgeOpenAPIOAuthStatusResponse,
)
from app.services.longbridge_openapi_oauth import LongbridgeOpenAPIOAuthError, LongbridgeOpenAPIOAuthService
from app.services.longbridge_service import LongbridgeExternalDataClient

router = APIRouter(prefix="/admin/longbridge/openapi", tags=["admin-longbridge-openapi"])


def _handle_oauth_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


def _external_url_for(request: Request, path: str) -> str:
    forwarded_proto = request.headers.get("x-forwarded-proto")
    forwarded_host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if forwarded_proto and forwarded_host:
        return f"{forwarded_proto.split(',')[0].strip()}://{forwarded_host.split(',')[0].strip()}{path}"

    parts = urlsplit(str(request.base_url))
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _status_response(service: LongbridgeOpenAPIOAuthService) -> LongbridgeOpenAPIOAuthStatusResponse:
    return LongbridgeOpenAPIOAuthStatusResponse(**service.status())


@router.get("/oauth/status", response_model=LongbridgeOpenAPIOAuthStatusResponse)
def get_longbridge_openapi_oauth_status(
    _auth_session: AuthSession = Depends(require_admin_session),
    service: LongbridgeOpenAPIOAuthService = Depends(get_longbridge_openapi_oauth_service),
) -> LongbridgeOpenAPIOAuthStatusResponse:
    return _status_response(service)


@router.post("/oauth/start", response_model=LongbridgeOpenAPIOAuthStartResponse)
def start_longbridge_openapi_oauth(
    request: Request,
    payload: LongbridgeOpenAPIOAuthStartRequest | None = Body(default=None),
    _auth_session: AuthSession = Depends(require_admin_session),
    service: LongbridgeOpenAPIOAuthService = Depends(get_longbridge_openapi_oauth_service),
) -> LongbridgeOpenAPIOAuthStartResponse:
    payload = payload or LongbridgeOpenAPIOAuthStartRequest()
    callback_path = "/api/admin/longbridge/openapi/oauth/callback"
    redirect_uri = (payload.redirect_uri or _external_url_for(request, callback_path)).strip()
    try:
        return LongbridgeOpenAPIOAuthStartResponse(**service.start_authorization(redirect_uri, payload.scope))
    except LongbridgeOpenAPIOAuthError as exc:
        raise _handle_oauth_error(exc) from exc


@router.post("/oauth/complete", response_model=LongbridgeOpenAPIOAuthMutationResponse)
def complete_longbridge_openapi_oauth_post(
    payload: LongbridgeOpenAPIOAuthCompleteRequest,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: LongbridgeOpenAPIOAuthService = Depends(get_longbridge_openapi_oauth_service),
) -> LongbridgeOpenAPIOAuthMutationResponse:
    try:
        service.complete_authorization(payload.code, payload.state)
    except LongbridgeOpenAPIOAuthError as exc:
        raise _handle_oauth_error(exc) from exc
    return LongbridgeOpenAPIOAuthMutationResponse(
        success=True,
        message="LongBridge OAuth authorization completed",
        status=_status_response(service),
    )


@router.get("/oauth/callback", response_class=HTMLResponse)
def complete_longbridge_openapi_oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    service: LongbridgeOpenAPIOAuthService = Depends(get_longbridge_openapi_oauth_service),
) -> HTMLResponse:
    if error:
        return HTMLResponse(
            f"<html><body><h2>LongBridge OAuth 授权失败</h2><p>{escape(error_description or error)}</p></body></html>",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if not code or not state:
        return HTMLResponse(
            "<html><body><h2>LongBridge OAuth 授权失败</h2><p>缺少 code 或 state。</p></body></html>",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    try:
        service.complete_authorization(code, state)
    except LongbridgeOpenAPIOAuthError as exc:
        return HTMLResponse(
            f"<html><body><h2>LongBridge OAuth 授权失败</h2><p>{escape(str(exc))}</p></body></html>",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return HTMLResponse(
        "<html><body><h2>LongBridge OAuth 授权成功</h2><p>你可以关闭这个页面，回到 IBKR Show 管理后台继续健康检查。</p></body></html>"
    )


@router.post("/oauth/refresh", response_model=LongbridgeOpenAPIOAuthMutationResponse)
def refresh_longbridge_openapi_oauth(
    _auth_session: AuthSession = Depends(require_admin_session),
    service: LongbridgeOpenAPIOAuthService = Depends(get_longbridge_openapi_oauth_service),
) -> LongbridgeOpenAPIOAuthMutationResponse:
    try:
        service.refresh_token()
    except LongbridgeOpenAPIOAuthError as exc:
        raise _handle_oauth_error(exc) from exc
    return LongbridgeOpenAPIOAuthMutationResponse(success=True, message="LongBridge OAuth token refreshed", status=_status_response(service))


@router.post("/oauth/disconnect", response_model=LongbridgeOpenAPIOAuthMutationResponse)
def disconnect_longbridge_openapi_oauth(
    _auth_session: AuthSession = Depends(require_admin_session),
    service: LongbridgeOpenAPIOAuthService = Depends(get_longbridge_openapi_oauth_service),
) -> LongbridgeOpenAPIOAuthMutationResponse:
    service.disconnect()
    return LongbridgeOpenAPIOAuthMutationResponse(success=True, message="LongBridge OAuth token cleared", status=_status_response(service))


@router.get("/health", response_model=LongbridgeOpenAPIHealthResponse)
def get_longbridge_openapi_health(
    _auth_session: AuthSession = Depends(require_admin_session),
    service: LongbridgeOpenAPIOAuthService = Depends(get_longbridge_openapi_oauth_service),
    client: LongbridgeExternalDataClient = Depends(get_longbridge_external_data_client),
) -> LongbridgeOpenAPIHealthResponse:
    health = client.health()
    sdk = client._sdk
    sdk_oauth_supported = bool(
        sdk
        and hasattr(sdk, "OAuthBuilder")
        and hasattr(sdk.Config, "from_oauth")
        and hasattr(sdk.HttpClient, "from_oauth")
    )
    can_initialize_config = False
    if health.get("enabled") and sdk_oauth_supported:
        try:
            client._get_config()
            can_initialize_config = True
        except Exception:
            can_initialize_config = False
    return LongbridgeOpenAPIHealthResponse(
        enabled=bool(health.get("enabled")),
        configured=bool(health.get("configured")),
        sdk_loaded=bool(health.get("sdk_loaded")),
        sdk_oauth_supported=sdk_oauth_supported,
        oauth_connected=bool(health.get("oauth_connected")),
        can_initialize_config=can_initialize_config,
        message=str(health.get("message") or ""),
        oauth_status=_status_response(service),
    )
